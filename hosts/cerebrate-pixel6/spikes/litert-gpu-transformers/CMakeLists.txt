# Segmentation and Labeling Lane, Step 2A: LiteRT 2.3.0 builds (see README.md).
cmake_minimum_required(VERSION 3.20)
project(litert_bench LANGUAGES CXX C)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_subdirectory("/tmp/litert_sdk_2.3.0/litert_cc_sdk" "/tmp/litert_sdk_2.3.0/litert_cc_sdk/build")
include_directories("/tmp/litert_sdk_2.3.0/litert_cc_sdk")

# The unchanged 2.2.0-era harness, rebuilt against 2.3.0.
add_executable(litert_bench ${CMAKE_CURRENT_SOURCE_DIR}/../litert-compiled-correctness/main.cc)
# 2.3.0: the SDK headers inline absl flat_hash_map, but litert_cc_api does not
# link absl::raw_hash_set, so link it here.
target_link_libraries(litert_bench litert_cc_api absl::raw_hash_set absl::hash android log)

add_executable(litert_c_canary canary.cc)
target_link_libraries(litert_c_canary litert_cc_api absl::raw_hash_set absl::hash android log)

add_executable(litert_e2e bench.cc)
target_link_libraries(litert_e2e litert_cc_api absl::raw_hash_set absl::hash android log)

add_executable(litert_chain chain.cc)
target_link_libraries(litert_chain litert_cc_api absl::raw_hash_set absl::hash android log)
