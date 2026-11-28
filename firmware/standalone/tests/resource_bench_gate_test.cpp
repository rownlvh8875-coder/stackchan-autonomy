// SPDX-License-Identifier: MIT
#include "bench_gate.hpp"
#include <cassert>
#include <string_view>
using namespace stackchan::standalone;
void line(BenchGate& g,std::string_view s,int64_t at=100) {
  for(char c:s)g.feed(c,at);
}
int main() {
  {BenchGate g{0x1234,0};line(g,"START 00001234\r\n");assert(g.running());
   line(g,"STOP\n");assert(g.stopped() && !g.running());
   line(g,"START 00001234\n");assert(!g.running());}
  {BenchGate g{0x1234,0};line(g,"START 00001235\n");assert(g.stopped());}
  {BenchGate g{1,0};line(g,"STOP\n");assert(g.stopped());}
  {BenchGate g{1,0};line(g,"START 00000001");assert(!g.running());
   g.tick(60001);assert(g.stopped());line(g,"\n");assert(!g.running());}
  {BenchGate g{1,10};g.tick(9);assert(g.stopped());}
  {BenchGate g{1,0};line(g,"START 00000001\n");assert(g.running());
   g.tick(10101);assert(g.stopped());}
  {BenchGate g{1,0};line(g,"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx");assert(g.stopped());}
  {BenchGate g{1,0};line(g,"START 00000001\rX\n");assert(g.stopped());}
  {BenchGate g{0,0};line(g,"START 00000000\n");assert(g.stopped());}
}
