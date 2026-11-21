# Measure the voice response buffers with the model resident

1. Reproduce excess vector capacity with a maximum speech body read in
   1 KiB chunks. Bound each growth request by the validated response limit.
   Include the simultaneous question, raw speech body and decoded PCM in the
   memory preflight, preserving the existing headroom and TLS evidence gate.
2. Extend the existing gated resource bench. Use the production receiver and
   decoder on synthetic JSON and PCM, observe real capacities/placement and
   heap with both speech buffers live, then retain the decoded PCM for the
   existing inference test. Check permission between chunks. Report aggregate
   data only. TLS handshake and physical audio remain separate measurements.
3. Run focused and full host checks, obtain one independent final review, and
   record actual ESP32-S3 build and CI results on the existing branch and PR.
   Check the resulting bench image and factory backups offline for the next
   installation review. Device operations require the user's image-specific
   approval under the original project brief.
