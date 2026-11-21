// SPDX-License-Identifier: MIT
// Narrow C ABI double for pinned IDF6.1 Mbed TLS4.1 PSA Crypto1.2, not hashing.
#pragma once
#include <stddef.h>
#include <stdint.h>
typedef int32_t psa_status_t;
typedef uint32_t psa_algorithm_t;
#define PSA_SUCCESS ((psa_status_t)0)
#define PSA_ALG_SHA_256 ((psa_algorithm_t)0x02000009)
extern "C" psa_status_t psa_crypto_init(void);
extern "C" psa_status_t psa_hash_compute(psa_algorithm_t,const uint8_t*,size_t,uint8_t*,size_t,size_t*);
