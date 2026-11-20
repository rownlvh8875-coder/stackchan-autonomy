// SPDX-License-Identifier: MIT
// P-256 ECDH, HKDF-SHA256 and AES-256-GCM from PSA Crypto / ESP-IDF v6.1.
// There is no USB, GPIO, LCD initialization, NVS write, Wi-Fi or API call.
#include "k151_secure_pc_setup.hpp"

#include <algorithm>
#include <array>
#include <cstring>
#include <limits>
#include <string_view>

namespace stackchan::standalone {
namespace {
constexpr std::array<uint8_t,4> kDeviceMagic{'K','S','D','1'};
constexpr std::array<uint8_t,4> kPcMagic{'K','S','P','1'};
constexpr std::array<uint8_t,4> kSealedMagic{'K','S','E','1'};
constexpr std::array<uint8_t,4> kPayloadMagic{'K','S','C','1'};
constexpr uint8_t kProtocolVersion=1;
constexpr size_t kEncryptedHeader=19;
constexpr char kKeyLabel[]="K151-SCPS-v1/aes256gcm/";
constexpr char kSasLabel[]="K151-SCPS-v1/sas/";
constexpr uint32_t kSasModulus=100000000;

void wipe(void* ptr,size_t n) noexcept {
  auto* const p=static_cast<volatile uint8_t*>(ptr);
  for(size_t i=0;i<n;++i)p[i]=0;
}
bool valid_text(std::span<const char> s,bool printable_space) {
  for(const char c:s) {
    const auto b=static_cast<uint8_t>(c);
    if(b < (printable_space?0x20:0x21) || b>0x7e) return false;
  }
  return true;
}
bool is_all_zero(std::span<const uint8_t> bytes) {
  return std::all_of(bytes.begin(),bytes.end(),[](uint8_t b){return b==0;});
}
} // namespace

void PairingCredentials::clear() noexcept {
  wipe(ssid_.data(),ssid_.size());
  wipe(password_.data(),password_.size());
  wipe(key_.data(),key_.size());
  ssid_len_=password_len_=key_len_=0;
}

const char* K151SecurePcSetup::compiled_link_marker() {
  return "SCPS ephemeral P-256 ECDH/HKDF/AES256-GCM linked; NOT STARTED";
}

bool K151SecurePcSetup::valid_time(uint64_t now) const {
  return started_ && !fault_ && !consumed_ && !stop_.load() &&
         now>=began_ms_ && now>=last_ms_ && now-began_ms_<kSessionMs;
}

bool K151SecurePcSetup::fail() { stop(); fault_=true; return false; }

void K151SecurePcSetup::stop() {
  if(private_key_!=0) {
    (void)psa_destroy_key(private_key_);
    private_key_=0;
  }
  wipe(device_hello_.data(),device_hello_.size());
  wipe(pc_hello_.data(),pc_hello_.size());
  wipe(aes_key_.data(),aes_key_.size());
  exchanged_=false;
  consumed_=true;
}

bool K151SecurePcSetup::device_hello(uint64_t now,bool owner_window,
                                     bool trusted_local_display,
                                     std::array<uint8_t,kHelloBytes>& out) {
  out.fill(0);
  if(started_ || consumed_ || fault_ || stop_.load() || !owner_window ||
     !trusted_local_display || now>UINT64_MAX-kSessionMs) return false;
  started_=true;
  began_ms_=last_ms_=now;
  if(psa_crypto_init()!=PSA_SUCCESS) return fail();
  psa_key_attributes_t attributes=PSA_KEY_ATTRIBUTES_INIT;
  psa_set_key_type(&attributes,PSA_KEY_TYPE_ECC_KEY_PAIR(PSA_ECC_FAMILY_SECP_R1));
  psa_set_key_bits(&attributes,256);
  psa_set_key_usage_flags(&attributes,PSA_KEY_USAGE_DERIVE);
  psa_set_key_algorithm(&attributes,PSA_ALG_ECDH);
  const psa_status_t made=psa_generate_key(&attributes,&private_key_);
  psa_reset_key_attributes(&attributes);
  if(made!=PSA_SUCCESS) return fail();
  device_hello_[0]='K';device_hello_[1]='S';device_hello_[2]='D';device_hello_[3]='1';
  device_hello_[4]=kProtocolVersion;
  size_t written=0;
  if(psa_export_public_key(private_key_,device_hello_.data()+5,65,&written)!=PSA_SUCCESS ||
     written!=65 || device_hello_[5]!=4) return fail();
  if(psa_generate_random(device_hello_.data()+70,16)!=PSA_SUCCESS ||
     is_all_zero({device_hello_.data()+70,16})) return fail();
  out=device_hello_;
  return true;
}

bool K151SecurePcSetup::derive(std::span<const uint8_t> shared,
                               const char* domain,uint8_t* out,size_t n) {
  std::array<uint8_t,32> salt{};
  std::copy_n(device_hello_.data()+70,16,salt.begin());
  std::copy_n(pc_hello_.data()+70,16,salt.begin()+16);
  std::array<uint8_t,256> info{};
  const size_t label_len=std::strlen(domain);
  const size_t length=label_len+130;
  if(length>info.size())return false;
  std::copy_n(reinterpret_cast<const uint8_t*>(domain),label_len,info.begin());
  std::copy_n(device_hello_.data()+5,65,info.begin()+label_len);
  std::copy_n(pc_hello_.data()+5,65,info.begin()+label_len+65);
  psa_key_derivation_operation_t derivation=PSA_KEY_DERIVATION_OPERATION_INIT;
  const bool okay =
       psa_key_derivation_setup(&derivation,PSA_ALG_HKDF(PSA_ALG_SHA_256))==PSA_SUCCESS &&
       psa_key_derivation_input_bytes(&derivation,PSA_KEY_DERIVATION_INPUT_SALT,
                                       salt.data(),salt.size())==PSA_SUCCESS &&
       psa_key_derivation_input_bytes(&derivation,PSA_KEY_DERIVATION_INPUT_SECRET,
                                       shared.data(),shared.size())==PSA_SUCCESS &&
       psa_key_derivation_input_bytes(&derivation,PSA_KEY_DERIVATION_INPUT_INFO,
                                       info.data(),length)==PSA_SUCCESS &&
       psa_key_derivation_output_bytes(&derivation,out,n)==PSA_SUCCESS;
  (void)psa_key_derivation_abort(&derivation);
  wipe(info.data(),info.size());
  wipe(salt.data(),salt.size());
  return okay;
}

bool K151SecurePcSetup::accept_pc_hello(uint64_t now,bool owner_window,
                        std::span<const uint8_t> hello,std::array<char,9>& sas) {
  sas.fill(0);
  if(!owner_window || !valid_time(now) || exchanged_ || hello.size()!=kHelloBytes ||
     !std::equal(kPcMagic.begin(),kPcMagic.end(),hello.begin()) ||
     hello[4]!=kProtocolVersion || hello[5]!=4 ||
     is_all_zero(hello.subspan(70,16)) ||
     std::equal(hello.begin()+5,hello.begin()+70,device_hello_.begin()+5))return fail();
  std::copy(hello.begin(),hello.end(),pc_hello_.begin());
  std::array<uint8_t,32> shared{};
  size_t written=0;
  const psa_status_t agreement=psa_raw_key_agreement(
      PSA_ALG_ECDH,private_key_,pc_hello_.data()+5,65,
      shared.data(),shared.size(),&written);
  if(agreement!=PSA_SUCCESS || written!=32) {
    wipe(shared.data(),shared.size());return fail();
  }
  std::array<uint8_t,8> digits{};
  const bool okay=derive(shared,kKeyLabel,aes_key_.data(),aes_key_.size()) &&
                   derive(shared,kSasLabel,digits.data(),digits.size());
  wipe(shared.data(),shared.size());
  // ECDH private key is destroyed as soon as all derived material exists.
  if(private_key_!=0){(void)psa_destroy_key(private_key_);private_key_=0;}
  if(!okay)return fail();
  uint64_t number=0;
  for(uint8_t b:digits)number=(number<<8U)|b;
  wipe(digits.data(),digits.size());
  uint32_t value=static_cast<uint32_t>(number%kSasModulus);
  for(int i=7;i>=0;--i){sas[static_cast<size_t>(i)]=static_cast<char>('0'+(value%10));value/=10;}
  sas[8]='\0';
  last_ms_=now;
  exchanged_=true;
  return true;
}

bool K151SecurePcSetup::open_sealed(uint64_t now,bool owner_window,
                                   bool sas_confirmed_on_local_screen,
                                   std::span<const uint8_t> sealed,
                                   PairingCredentials& output) {
  output.clear();
  if(!valid_time(now) || !exchanged_ || !owner_window ||
     !sas_confirmed_on_local_screen ||
     sealed.size()<kEncryptedHeader+16 || sealed.size()>kMaxSealedBytes ||
     !std::equal(kSealedMagic.begin(),kSealedMagic.end(),sealed.begin()) ||
     sealed[4]!=kProtocolVersion) return fail();
  const size_t encrypted_size=static_cast<size_t>(sealed[17])|
                 (static_cast<size_t>(sealed[18])<<8U);
  if(encrypted_size<=16 || encrypted_size>kMaxPayload+16 ||
     sealed.size()!=kEncryptedHeader+encrypted_size ||
     is_all_zero(sealed.subspan(5,12)))return fail();
  // Single-use key and IV. Never try to decrypt multiple candidate packets.
  consumed_=true;
  psa_key_attributes_t attributes=PSA_KEY_ATTRIBUTES_INIT;
  psa_set_key_type(&attributes,PSA_KEY_TYPE_AES);
  psa_set_key_bits(&attributes,256);
  psa_set_key_usage_flags(&attributes,PSA_KEY_USAGE_DECRYPT);
  psa_set_key_algorithm(&attributes,PSA_ALG_GCM);
  psa_key_id_t temp_key=0;
  const psa_status_t imported=psa_import_key(&attributes,aes_key_.data(),
                                            aes_key_.size(),&temp_key);
  psa_reset_key_attributes(&attributes);
  if(imported!=PSA_SUCCESS)return fail();
  std::array<uint8_t,kMaxPayload> clear{};
  std::array<uint8_t,2*kHelloBytes+kEncryptedHeader> aad{};
  std::copy(device_hello_.begin(),device_hello_.end(),aad.begin());
  std::copy(pc_hello_.begin(),pc_hello_.end(),aad.begin()+kHelloBytes);
  std::copy_n(sealed.data(),kEncryptedHeader,aad.begin()+2*kHelloBytes);
  size_t clear_length=0;
  const psa_status_t decrypted=psa_aead_decrypt(
      temp_key,PSA_ALG_GCM,sealed.data()+5,12,
      aad.data(),aad.size(),sealed.data()+kEncryptedHeader,encrypted_size,
      clear.data(),clear.size(),&clear_length);
  (void)psa_destroy_key(temp_key);
  wipe(aad.data(),aad.size());
  wipe(aes_key_.data(),aes_key_.size());
  if(decrypted!=PSA_SUCCESS || clear_length<8 || clear_length>kMaxPayload ||
     !std::equal(kPayloadMagic.begin(),kPayloadMagic.end(),clear.begin()) ||
     clear[4]!=kProtocolVersion) {wipe(clear.data(),clear.size());return fail();}
  const size_t ssidlen=clear[5],passlen=clear[6],keylen=clear[7];
  if(ssidlen==0 || ssidlen>32 || passlen<8 || passlen>64 ||
     keylen<16 || keylen>220 || clear_length!=8+ssidlen+passlen+keylen){
    wipe(clear.data(),clear.size());return fail();
  }
  const auto ssid=std::span<const uint8_t>(clear.data()+8,ssidlen);
  const auto pass=std::span<const char>(reinterpret_cast<const char*>(clear.data()+8+ssidlen),passlen);
  const auto api=std::span<const char>(reinterpret_cast<const char*>(clear.data()+8+ssidlen+passlen),keylen);
  bool safe=std::all_of(ssid.begin(),ssid.end(),[](uint8_t b){return b>=0x20 && b!=0x7f;}) &&
            valid_text(pass,true) && valid_text(api,false);
  if(passlen==64) safe=safe && std::all_of(pass.begin(),pass.end(),[](char c){
    return (c>='0'&&c<='9')||(c>='a'&&c<='f')||(c>='A'&&c<='F');
  });
  if(!safe){wipe(clear.data(),clear.size());return fail();}
  std::copy(ssid.begin(),ssid.end(),output.ssid_.begin());
  std::copy(pass.begin(),pass.end(),output.password_.begin());
  std::copy(api.begin(),api.end(),output.key_.begin());
  output.ssid_len_=ssidlen;output.password_len_=passlen;output.key_len_=keylen;
  wipe(clear.data(),clear.size());
  stop(); // Make both transcript and key material non-reusable.
  if (stop_.load()) {output.clear();return false;}
  return true;
}

} // namespace stackchan::standalone
