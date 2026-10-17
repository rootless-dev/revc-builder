# Included by the mpg123 build through CMAKE_PROJECT_mpg123_INCLUDE (vcbuilder/deps.py).
#
# mpg123's CMake port builds libmpg123.dylib without an SOVERSION, while reVC bundles and
# links libmpg123.0.dylib, the name the autotools build has always produced (spec F2).
# The call is deferred to the end of mpg123's top-level CMakeLists.txt, after the target
# exists, so the mpg123 sources stay untouched.
cmake_language(DEFER DIRECTORY "${CMAKE_SOURCE_DIR}"
    CALL set_target_properties libmpg123 PROPERTIES SOVERSION 0)
