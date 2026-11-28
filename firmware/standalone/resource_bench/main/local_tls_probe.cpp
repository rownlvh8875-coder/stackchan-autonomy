// SPDX-License-Identifier: MIT
#include "local_tls_probe.hpp"

#include <algorithm>
#include <array>
#include <cstring>
#include <mbedtls/pk.h>
#include <mbedtls/ssl.h>
#include <mbedtls/x509_crt.h>
#include <psa/crypto.h>
#include <string_view>

namespace stackchan::standalone {
namespace {

constexpr char kIssuer[] = "CN=K151 Local Memory Bench CA";
constexpr char kLeaf[] = "CN=bench.stackchan.invalid";
constexpr unsigned kMaxPumpRounds = 128;

class MemoryFifo {
 public:
  int push(const unsigned char* data, size_t size) {
    const size_t count = std::min(size, bytes_.size() - used_);
    if (!count) return size ? MBEDTLS_ERR_SSL_WANT_WRITE : 0;
    std::memcpy(bytes_.data() + used_, data, count);
    used_ += count;
    return static_cast<int>(count);
  }

  int pop(unsigned char* data, size_t size) {
    const size_t count = std::min(size, used_);
    if (!count) return size ? MBEDTLS_ERR_SSL_WANT_READ : 0;
    std::memcpy(data, bytes_.data(), count);
    used_ -= count;
    std::memmove(bytes_.data(), bytes_.data() + count, used_);
    return static_cast<int>(count);
  }

 private:
  std::array<unsigned char, 1024> bytes_{};
  size_t used_ = 0;
};

struct MemoryBio {
  MemoryFifo& input;
  MemoryFifo& output;
  static int send(void* context, const unsigned char* data, size_t size) {
    return static_cast<MemoryBio*>(context)->output.push(data, size);
  }
  static int receive(void* context, unsigned char* data, size_t size) {
    return static_cast<MemoryBio*>(context)->input.pop(data, size);
  }
};

struct EphemeralKey {
  mbedtls_svc_key_id_t id = MBEDTLS_SVC_KEY_ID_INIT;
  mbedtls_pk_context pk;

  EphemeralKey() { mbedtls_pk_init(&pk); }
  ~EphemeralKey() {
    mbedtls_pk_free(&pk);
    if (!mbedtls_svc_key_id_is_null(id)) (void)psa_destroy_key(id);
  }
  EphemeralKey(const EphemeralKey&) = delete;
  EphemeralKey& operator=(const EphemeralKey&) = delete;

  bool generate() {
    psa_key_attributes_t attr = PSA_KEY_ATTRIBUTES_INIT;
    psa_set_key_lifetime(&attr, PSA_KEY_LIFETIME_VOLATILE);
    psa_set_key_type(&attr, PSA_KEY_TYPE_ECC_KEY_PAIR(PSA_ECC_FAMILY_SECP_R1));
    psa_set_key_bits(&attr, 256);
    // Follow this SDK's ECDSA mode (randomized or deterministic). TLS suite
    // selection checks that the opaque PSA key permits the SDK's exact algorithm.
    psa_set_key_algorithm(&attr, MBEDTLS_PK_ALG_ECDSA(PSA_ALG_SHA_256));
    psa_set_key_usage_flags(&attr, PSA_KEY_USAGE_SIGN_HASH);
    const auto status = psa_generate_key(&attr, &id);
    psa_reset_key_attributes(&attr);
    return status == PSA_SUCCESS && mbedtls_pk_wrap_psa(&pk, id) == 0;
  }
};

struct CertificateWriter {
  mbedtls_x509write_cert ctx;
  CertificateWriter() { mbedtls_x509write_crt_init(&ctx); }
  ~CertificateWriter() { mbedtls_x509write_crt_free(&ctx); }
};

struct Certificate {
  mbedtls_x509_crt chain;
  Certificate() { mbedtls_x509_crt_init(&chain); }
  ~Certificate() { mbedtls_x509_crt_free(&chain); }
  Certificate(const Certificate&) = delete;
  Certificate& operator=(const Certificate&) = delete;
};

bool certificate(mbedtls_x509_crt& out, EphemeralKey& key, EphemeralKey& issuer,
                 const char* subject, unsigned char serial, bool ca) {
  CertificateWriter writer;
  auto* ctx = &writer.ctx;
  mbedtls_x509write_crt_set_version(ctx, MBEDTLS_X509_CRT_VERSION_3);
  mbedtls_x509write_crt_set_md_alg(ctx, MBEDTLS_MD_SHA256);
  mbedtls_x509write_crt_set_subject_key(ctx, &key.pk);
  mbedtls_x509write_crt_set_issuer_key(ctx, &issuer.pk);
  if (mbedtls_x509write_crt_set_subject_name(ctx, subject) ||
      mbedtls_x509write_crt_set_issuer_name(ctx, kIssuer) ||
      mbedtls_x509write_crt_set_serial_raw(ctx, &serial, 1) ||
      mbedtls_x509write_crt_set_validity(ctx, "19700101000000", "20990101000000") ||
      mbedtls_x509write_crt_set_basic_constraints(ctx, ca ? 1 : 0, ca ? 0 : -1) ||
      mbedtls_x509write_crt_set_key_usage(ctx, ca ? MBEDTLS_X509_KU_KEY_CERT_SIGN
                                                : MBEDTLS_X509_KU_DIGITAL_SIGNATURE)) return false;
  // The buffer holds only the public certificate. The volatile private key
  // is used through PSA and is never exported.
  std::array<unsigned char, 768> der{};
  const int len = mbedtls_x509write_crt_der(ctx, der.data(), der.size());
  return len > 0 && static_cast<size_t>(len) <= der.size() &&
         mbedtls_x509_crt_parse_der(&out, der.data() + der.size() - len, len) == 0;
}

bool would_block(int rc) {
  return rc == MBEDTLS_ERR_SSL_WANT_READ || rc == MBEDTLS_ERR_SSL_WANT_WRITE;
}

struct TlsEndpoint {
  mbedtls_ssl_config config;
  mbedtls_ssl_context connection;

  TlsEndpoint() {
    mbedtls_ssl_config_init(&config);
    mbedtls_ssl_init(&connection);
  }
  ~TlsEndpoint() {
    mbedtls_ssl_free(&connection);
    mbedtls_ssl_config_free(&config);
  }
  TlsEndpoint(const TlsEndpoint&) = delete;
  TlsEndpoint& operator=(const TlsEndpoint&) = delete;

  bool configure(int endpoint) {
    if (mbedtls_ssl_config_defaults(&config, endpoint, MBEDTLS_SSL_TRANSPORT_STREAM,
                                    MBEDTLS_SSL_PRESET_DEFAULT)) return false;
    mbedtls_ssl_conf_min_tls_version(&config, MBEDTLS_SSL_VERSION_TLS1_2);
    mbedtls_ssl_conf_max_tls_version(&config, MBEDTLS_SSL_VERSION_TLS1_2);
    return true;
  }

  bool open(MemoryBio& bio) {
    if (mbedtls_ssl_setup(&connection, &config)) return false;
    mbedtls_ssl_set_bio(&connection, &bio, MemoryBio::send, MemoryBio::receive, nullptr);
    return true;
  }

  int handshake_step() {
    if (ready()) return 0;
    const int rc = mbedtls_ssl_handshake_step(&connection);
    return would_block(rc) ? 0 : rc;
  }

  bool ready() { return mbedtls_ssl_is_handshake_over(&connection); }
};
} // namespace

struct LocalTlsProbe::Pair {
  MemoryFifo to_client, to_server;
  MemoryBio client_bio{to_client, to_server};
  MemoryBio server_bio{to_server, to_client};
  EphemeralKey leaf_key;
  // Endpoints are destroyed first, as their configs borrow these identities.
  Certificate root, leaf;
  TlsEndpoint client, server;

  bool prepare_identity(const std::function<bool()>& allowed) {
    EphemeralKey issuer;
    return psa_crypto_init() == PSA_SUCCESS && allowed() && issuer.generate() &&
           allowed() && leaf_key.generate() && allowed() &&
           certificate(root.chain, issuer, issuer, kIssuer, 1, true) && allowed() &&
           certificate(leaf.chain, leaf_key, issuer, kLeaf, 2, false) && allowed();
  }

  bool prepare_endpoints(const char* name) {
    if (!client.configure(MBEDTLS_SSL_IS_CLIENT) || !server.configure(MBEDTLS_SSL_IS_SERVER))
      return false;
    mbedtls_ssl_conf_ca_chain(&client.config, &root.chain, nullptr);
    mbedtls_ssl_conf_authmode(&client.config, MBEDTLS_SSL_VERIFY_REQUIRED);
    if (mbedtls_ssl_conf_own_cert(&server.config, &leaf.chain, &leaf_key.pk)) return false;
    return client.open(client_bio) && server.open(server_bio) &&
           mbedtls_ssl_set_hostname(&client.connection, name) == 0;
  }

  bool handshake(const std::function<bool()>& allowed, int& sdk_error) {
    for (unsigned round = 0; round < kMaxPumpRounds; ++round) {
      if (!allowed()) return false;
      sdk_error = client.handshake_step();
      if (sdk_error != 0 || !allowed()) return false;
      sdk_error = server.handshake_step();
      if (sdk_error != 0) return false;
      if (client.ready() && server.ready())
        return allowed() && mbedtls_ssl_get_verify_result(&client.connection) == 0 &&
               mbedtls_ssl_get_version_number(&client.connection) == MBEDTLS_SSL_VERSION_TLS1_2;
    }
    return false;
  }

  bool check_application_record(const std::function<bool()>& allowed) {
    constexpr std::string_view message = "K151 local synthetic TLS record";
    const auto* source = reinterpret_cast<const unsigned char*>(message.data());
    std::array<unsigned char, message.size()> received{};
    bool sent = false;
    size_t used = 0;
    for (unsigned round = 0; round < kMaxPumpRounds; ++round) {
      if (!allowed()) return false;
      if (!sent) {
        const int rc = mbedtls_ssl_write(&server.connection, source, message.size());
        if (rc == static_cast<int>(message.size())) sent = true;
        else if (!would_block(rc)) return false;
      }
      if (!allowed()) return false;
      const int rc = mbedtls_ssl_read(&client.connection, received.data() + used,
                                      received.size() - used);
      if (would_block(rc)) continue;
      if (rc <= 0 || static_cast<size_t>(rc) > received.size() - used) return false;
      used += static_cast<size_t>(rc);
      if (used == received.size())
        return sent && allowed() && std::equal(received.begin(), received.end(), source);
    }
    return false;
  }
};

LocalTlsProbe::LocalTlsProbe() = default;
LocalTlsProbe::~LocalTlsProbe() = default;

bool LocalTlsProbe::run(const std::function<bool()>& allowed, const char* hostname) {
  if (attempted_) return false;
  attempted_ = true;
  if (!allowed || !hostname || !allowed()) return false;
  auto pending = std::make_unique<Pair>();
  stage_ = "identity";
  if (!pending->prepare_identity(allowed)) return false;
  stage_ = "endpoints";
  if (!pending->prepare_endpoints(hostname) || !allowed()) return false;
  stage_ = "handshake";
  if (!pending->handshake(allowed, handshake_error_)) return false;
  stage_ = "application_record";
  if (!pending->check_application_record(allowed)) return false;
  pair_ = std::move(pending);
  stage_ = "established";
  return true;
}

} // namespace stackchan::standalone
