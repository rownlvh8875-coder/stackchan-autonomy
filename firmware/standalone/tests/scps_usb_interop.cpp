// Cross-language SCPS framing bytes: C++ codec emits deterministic hex only.
// No USB device, crypto key, microphone or secret data is ever used.
#include "scps_usb_wire.hpp"
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <vector>
using namespace stackchan::standalone::scpswire;

static void emit(Op op, const std::vector<uint8_t>& payload) {
  const auto packet=encode(op,payload);
  if(!packet) std::abort();
  for(const uint8_t b : *packet) std::printf("%02x",static_cast<unsigned>(b));
  std::printf("\n");
}
int main() {
  std::vector<uint8_t> hello(86);
  for(size_t i=0;i<hello.size();++i)hello[i]=static_cast<uint8_t>(i);
  std::vector<uint8_t> sealed(35);
  for(size_t i=0;i<sealed.size();++i)
    sealed[i]=static_cast<uint8_t>(0x90U+i);
  emit(Op::device_hello,hello);
  emit(Op::pc_hello,hello);
  emit(Op::sealed_credentials,sealed);
  emit(Op::completed,{});
  emit(Op::stop,{});
  emit(Op::local_setup_fault,{static_cast<uint8_t>(SetupFailure::sensor_read)});
}
