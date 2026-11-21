# Add a socket-free TLS phase to the K151 resource bench

1. Build Mbed TLS 4.1.0 for the host and use a C++ fixture
   to exercise a real certificate-verified TLS 1.2 handshake, application
   traffic, rejection of the wrong name, cancellation and finite progress.
2. Reuse the existing nonce gate, model, PCM and wire decoder workload.
   Keep both real TLS contexts resident while sampling the known speech
   buffer overlap. Report handshake and overlap stages separately. Ephemeral
   test certificate keys exist only in volatile PSA storage. The fixture
   has no sockets and the production trust store and gate remain untouched.
3. Review the change, run host checks and the pinned S3 build, and record the
   actual CI result on PR #3. The extra in-process server affects the
   watermark. Production certificate-chain and network/codec loads still
   need measurement. A new physical image requires its own approved scope.
