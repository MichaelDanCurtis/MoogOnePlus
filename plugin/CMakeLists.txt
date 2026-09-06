cmake_minimum_required(VERSION 3.24)
project(moogone_clap VERSION 0.1.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# CLAP headers are fetched rather than vendored: they are a third party's and this
# repository does not carry other people's source.
include(FetchContent)
FetchContent_Declare(clap
  GIT_REPOSITORY https://github.com/free-audio/clap.git
  GIT_TAG        1.2.2
  GIT_SHALLOW    TRUE)
FetchContent_MakeAvailable(clap)

add_library(moogone_clap MODULE
  src/plugin.cpp
  src/osc.cpp
  src/sender.cpp
  src/audio.cpp
  src/receiver.cpp)

target_link_libraries(moogone_clap PRIVATE clap)
target_include_directories(moogone_clap PRIVATE src)

set_target_properties(moogone_clap PROPERTIES
  BUNDLE TRUE
  OUTPUT_NAME "MoogOne"
  SUFFIX ""
  PREFIX "")

if(APPLE)
  set_target_properties(moogone_clap PROPERTIES
    BUNDLE_EXTENSION "clap"
    MACOSX_BUNDLE_BUNDLE_NAME "MoogOne"
    MACOSX_BUNDLE_GUI_IDENTIFIER "dev.moogoneplus.clap"
    MACOSX_BUNDLE_BUNDLE_VERSION "${PROJECT_VERSION}")
endif()

# The OSC codec and the pacing interlock are pure and must be testable without a
# host: a bug in either reaches the instrument, and one of them can wedge it.
add_executable(moogone_clap_tests
  tests/test_main.cpp
  src/osc.cpp
  src/sender.cpp
  src/audio.cpp
  src/receiver.cpp)
target_include_directories(moogone_clap_tests PRIVATE src)
enable_testing()
add_test(NAME unit COMMAND moogone_clap_tests)

# A minimal host, so the plugin can be proven against the real instrument without
# opening a DAW.
add_executable(moogone_clap_host tests/host.cpp)
target_link_libraries(moogone_clap_host PRIVATE clap)
