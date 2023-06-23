# MIT License
#
# Copyright The SCons Foundation
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY
# KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
# WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

"""
Tool-specific initialization for newer versions of the Intel Fortran Compiler
for Linux/Windows (and possibly Mac OS X).

There normally shouldn't be any need to import this module directly.
It will usually be imported through the generic SCons.Tool.Tool()
selection method.
"""

import glob
import os
import re
import sys
import SCons.Defaults
from SCons.Scanner.Fortran import FortranScan
from .FortranCommon import add_all_to_env

is_windows = sys.platform == "win32"
is_win64 = is_windows and (
    os.environ["PROCESSOR_ARCHITECTURE"] == "AMD64"
    or (
        "PROCESSOR_ARCHITEW6432" in os.environ
        and os.environ["PROCESSOR_ARCHITEW6432"] == "AMD64"
    )
)
is_linux = sys.platform.startswith("linux")

if is_windows:
    import SCons.Tool.msvc


# Exceptions for this tool
class IntelFortranError(SCons.Errors.InternalError):
    pass


class MissingRegistryError(IntelFortranError):  # missing registry entry
    pass


class MissingDirError(IntelFortranError):  # dir not found
    pass


class NoRegistryModuleError(IntelFortranError):  # can't read registry at all
    pass


def get_intel_registry_value(valueName, version, abi=None, msvs=None):
    """
    Return a value from the Intel compiler registry tree. (Windows only)
    """
    regArch = {
        "x86_64": "EM64T_NATIVE",
        "amd64": "EM64T_NATIVE",
        "em64t": "EM64T_NATIVE",
        "x86": "IA32",
        "i386": "IA32",
        "ia32": "IA32",
    }
    path = get_registry_path(version)
    if abi is not None:
        path = f"{path}\\{regArch[abi]}"
    if msvs is not None:
        path = f"{path}\\{msvs}"
    try:
        k = SCons.Util.RegOpenKeyEx(SCons.Util.HKEY_LOCAL_MACHINE, path)
    except SCons.Util.RegError:
        regError = (
            f"{path} was not found in the registry, for Intel compiler version"
            f" {version}, abi='{abi}'"
        )
        raise MissingRegistryError(regError)
    try:
        v = SCons.Util.RegQueryValueEx(k, valueName)[0]
        return v
    except SCons.Util.RegError:
        regError = f"{path}\\{valueName} was not found in the registry."
        raise MissingRegistryError(regError)


def get_intel_buildversion(version):
    """
    Return the build number. (Windows only)
    """
    keyName = get_registry_path(version)
    try:
        key = SCons.Util.RegOpenKeyEx(SCons.Util.HKEY_LOCAL_MACHINE, keyName)
    except OSError:
        return []
    keySubVersionList = []
    i = 0
    while True:
        try:
            keySubVersionList.append(SCons.Util.RegEnumKey(key, i))
        except OSError:
            break
        i += 1
    keySubVersionList.sort()
    keySubVersion = keySubVersionList[
        len(keySubVersionList) - 1
    ]  # raises EnvironmentError
    return keySubVersion


def get_registry_path(version: str) -> str:
    """
    Return the registry path for the Intel compiler. (Windows only)
    """
    if int(version.split(".")[0]) < 2023:
        return f"Software\\Wow6432Node\\Intel\\Compilers\\Fortran\\{version}"
    else:
        # newer versions of the compiler use a different registry path
        return f"Software\\Wow6432Node\\Intel\\Compilers\\1AFortran\\{version}"


def extract_compiler_versions_from_registry(path: str) -> list:
    """
    Return a list of compiler versions from a registry path. (Windows only)
    """
    try:
        k = SCons.Util.RegOpenKeyEx(SCons.Util.HKEY_LOCAL_MACHINE, path)
    except OSError:
        return []
    i = 0
    versions = []
    while True:
        try:
            buildVersion = SCons.Util.RegEnumKey(k, i)
        except OSError:
            # reached the end of the list
            break
        try:
            # intel compiler versions are floats, skip all non-numeric entries
            _ = float(buildVersion)
            versions.append(buildVersion)
        except ValueError:
            pass
        i += 1
    return versions


def get_all_compiler_versions():
    """Returns a sorted list of strings, like "70" or "80" or "9.0"
    with most recent compiler version first.
    """
    versions = []
    if is_windows:
        # the locations of the compilers in the registry changed between 2019
        # and 2023. Compile a list of versions in both locations.
        # older versions
        keyName = "Software\\WoW6432Node\\Intel\\Compilers\\Fortran"
        versions = extract_compiler_versions_from_registry(keyName)
        # newer versions
        keyName = "Software\\WoW6432Node\\Intel\\Compilers\\1AFortran"
        versions.extend(extract_compiler_versions_from_registry(keyName))
        return sorted(versions, reverse=True)
    elif is_linux:
        for d in glob.glob("/opt/intel*/composer_xe_*"):
            # Typical dir here is /opt/intel/composer_xe_2011_sp1.11.344
            # The _sp1 is useless, the installers are named 2011.9.x, 2011.10.x, 2011.11.x
            m = re.search(r"([0-9]{0,4})(?:_sp\d*)?\.([0-9][0-9.]*)$", d)
            if m:
                versions.append("%s.%s" % (m.group(1), m.group(2)))
        for d in glob.glob("/opt/intel*/compilers_and_libraries_*"):
            # Typical dir here is /opt/intel/compilers_and_libraries_<year>.<version>.<subversion>
            m = re.search(r"([0-9]{0,4})(?:_sp\d*)?\.([0-9][0-9.]*)$", d)
            if m:
                versions.append("%s.%s" % (m.group(1), m.group(2)))
        return sorted(versions, reverse=True)


def get_intel_compiler_top(version, abi):
    """
    Return the main path to the top-level dir of the Intel compiler,
    using the given version.
    The compiler will be in <top>/bin/icl.exe (icc on linux),
    the include dir is <top>/include, etc.
    """
    top = None
    if is_windows:
        if not SCons.Util.can_read_reg:
            raise NoRegistryModuleError("No Windows registry module was found")
        top = get_intel_registry_value("ProductDir", version)
    elif is_linux:

        def find_in_2011style_dir(version):
            # The 2011 (compiler v12) dirs are inconsistent, so just redo the search from
            # get_all_compiler_versions and look for a match (search the newest form first)
            top = None
            for d in glob.glob("/opt/intel*/composer_xe_*"):
                # Typical dir here is /opt/intel/composer_xe_2011_sp1.11.344
                # The _sp1 is useless, the installers are named 2011.9.x, 2011.10.x, 2011.11.x
                m = re.search(r"([0-9]{0,4})(?:_sp\d*)?\.([0-9][0-9.]*)$", d)
                if m:
                    cur_ver = "%s.%s" % (m.group(1), m.group(2))
                    if cur_ver == version and (
                        os.path.exists(os.path.join(d, "bin", "ia32", "icc"))
                        or os.path.exists(os.path.join(d, "bin", "intel64", "icc"))
                    ):
                        top = d
                        break
            if not top:
                for d in glob.glob("/opt/intel*/composerxe-*"):
                    # Typical dir here is /opt/intel/composerxe-2011.4.184
                    m = re.search(r"([0-9][0-9.]*)$", d)
                    if (
                        m
                        and m.group(1) == version
                        and (
                            os.path.exists(os.path.join(d, "bin", "ia32", "icc"))
                            or os.path.exists(os.path.join(d, "bin", "intel64", "icc"))
                        )
                    ):
                        top = d
                        break
            return top

        def find_in_2017style_dir(version):
            # The 2017 (compiler v17) dirs are different again, so just redo the search from
            # get_all_compiler_versions and look for a match (search the newest form first)
            top = None
            version_stripped = str(int(float(version)))
            for d in glob.glob("/opt/intel*/compilers_and_libraries_*"):
                # Typical dir here is /opt/intel/compilers_and_libraries_<year>.<version>.<subversion>
                m = re.search(r"([0-9]{0,4})(?:_sp\d*)?\.([0-9][0-9.]*)$", d)
                if m:
                    cur_ver = "%s.%s" % (m.group(1), m.group(2))
                    if ((cur_ver == version) or (version_stripped in cur_ver)) and (
                        os.path.exists(os.path.join(d, "linux", "bin", "ia32", "icc"))
                        or os.path.exists(
                            os.path.join(d, "linux", "bin", "intel64", "icc")
                        )
                    ):
                        top = os.path.join(d, "linux")
                        break
            return top

        top = find_in_2011style_dir(version) or find_in_2017style_dir(version)
        if not top:
            raise MissingDirError(
                "Can't find version %s Intel compiler in %s (abi='%s')"
                % (version, top, abi)
            )
    return top


def generate(env, version=None, abi=None, topdir=None, verbose=0):
    r"""Add Builders and construction variables for the Intel Fortran compiler to an Environment.
    args:
      version: (string) compiler version to use, like "130, 140, 150"
      abi:     (string) 'ia32' or 'x86_64'
      topdir:  (string) compiler top installation dir, like
                         "C:\Program Files (x86)\Intel\Composer XE 2015"
                         "/opt/intel2015"
      verbose: (int)    if >0, prints compiler version used.
    """
    if is_windows:
        SCons.Tool.msvc.generate(env)

    # ifort supports Fortran 90 and Fortran 95
    # Additionally, ifort recognizes more file extensions.
    fscan = FortranScan("FORTRANPATH")
    SCons.Tool.SourceFileScanner.add_scanner(".i", fscan)
    SCons.Tool.SourceFileScanner.add_scanner(".i90", fscan)

    if 'FORTRANFILESUFFIXES' not in env:
        env['FORTRANFILESUFFIXES'] = [".i"]
    else:
        env['FORTRANFILESUFFIXES'].append(".i")

    if 'F90FILESUFFIXES' not in env:
        env['F90FILESUFFIXES'] = [".i90"]
    else:
        env['F90FILESUFFIXES'].append(".i90")

    vlist = get_all_compiler_versions()
    if not topdir and len(vlist) == 0:
        print("Intel Fortran compiler not configured. Could not find an installation.")
        return
    if verbose:
        print("Found installed Intel Fortran versions:")
        print(vlist)

    # Select the latest version if not specified, otherwise find the
    # first occurrence of a matching specified version
    if len(vlist) != 0:
        if not version:
            version = vlist[0]
        else:
            version_stripped = version.replace(".", "")
            for v in vlist:
                if version_stripped in v:
                    version = v
                    break
    if verbose:
        print("Selected Intel Fortran compiler version: " + version)

    if not abi:
        if is_win64 or is_linux:
            abi = "x86_64"
        else:
            abi = "ia32"

    if not topdir:
        topdir = get_intel_compiler_top(version, abi)
    elif topdir and not os.path.exists(topdir):
        topdir = get_intel_compiler_top(version, abi)

    if verbose:
        print("Found Intel Fortran compiler at: " + topdir)

    if topdir:
        archdir = {
            "x86_64": "intel64",
            "amd64": "intel64",
            "em64t": "intel64",
            "x86": "ia32",
            "i386": "ia32",
            "ia32": "ia32",
        }[
            abi
        ]  # for v11 and greater
        if os.path.exists(os.path.join(topdir, "bin", archdir)):
            bindir = os.path.join("bin", archdir)
            libdir = os.path.join("compiler", "lib", archdir)
            incdir = os.path.join("compiler", "include")
        else:
            bindir = "bin"
            libdir = "lib"
            incdir = "include"
        _ = os.path.join(incdir, archdir)
        binmkl = None
        libmkl = None
        incmkl = None
        if os.path.exists(os.path.join(topdir, "mkl", "bin", archdir)):
            binmkl = os.path.join("mkl", "bin", archdir)
            libmkl = os.path.join("mkl", "lib", archdir)
            incmkl = os.path.join("mkl", "include")

        # Get the directory where the compiler is found
        if is_windows:
            intelCompilerRedistPath = os.path.join(topdir, "redist", "intel64")
            if not os.path.isdir(intelCompilerRedistPath):
                intelCompilerRedistPath += "_win"
            intelCompilerRedistPath = os.path.join(intelCompilerRedistPath, "compiler")
        else:
            intelCompilerRedistPath = os.path.join(topdir, "lib", "intel64")
            if not os.path.isdir(intelCompilerRedistPath):
                intelCompilerRedistPath += "_lin"

        env["INTEL_FORTRAN_REDIST_DIR"] = intelCompilerRedistPath

        if verbose:
            print(
                "Intel Fortran compiler: using version %s, abi %s, in '%s/%s'"
                % (repr(version), abi, topdir, bindir)
            )
            if is_linux:
                # Show the actual compiler version by running the compiler.
                os.system("%s/%s/ifort --version" % (topdir, bindir))

        env["INTEL_FORTRAN_COMPILER_TOP"] = topdir
        paths = {"INCLUDE": incdir, "LIB": libdir, "PATH": bindir}
        for p in paths.keys():
            env.AppendENVPath(p, os.path.join(topdir, paths[p]))
        if binmkl:
            env.AppendENVPath("PATH", os.path.join(topdir, binmkl))
            env.AppendENVPath("INCLUDE", os.path.join(topdir, incmkl))
            env.AppendENVPath("LIB", os.path.join(topdir, libmkl))

        if is_windows:
            env.AppendENVPath(
                "PATH", os.path.join(topdir, "redist", archdir, "compiler")
            )
        elif is_linux:
            env.AppendENVPath("LD_LIBRARY_PATH", os.path.join(topdir, libdir))
            if binmkl:
                env.AppendENVPath("LD_LIBRARY_PATH", os.path.join(topdir, libmkl))

    add_all_to_env(env)

    fc = "ifort"

    for dialect in ["F77", "F90", "FORTRAN", "F95"]:
        env["%s" % dialect] = fc
        env["SH%s" % dialect] = "$%s" % dialect
        if env["PLATFORM"] == "posix":
            env["SH%sFLAGS" % dialect] = SCons.Util.CLVar("$%sFLAGS -fPIC" % dialect)

    if env["PLATFORM"] == "win32":
        # On Windows, the ifort compiler specifies the object on the
        # command line with -object:, not -o.  Massage the necessary
        # command-line construction variables.
        for dialect in ["F77", "F90", "FORTRAN", "F95"]:
            for var in [
                "%sCOM" % dialect,
                "%sPPCOM" % dialect,
                "SH%sCOM" % dialect,
                "SH%sPPCOM" % dialect,
            ]:
                env[var] = env[var].replace("-o $TARGET", "-object:$TARGET")
        env["FORTRANMODDIRPREFIX"] = "/module:"
    else:
        env["FORTRANMODDIRPREFIX"] = "-module "
    env["FORTRANMODDIR"] = "${TARGET.dir}"
    env["F90PATH"] = "${TARGET.dir}"


def exists(env):
    return env.Detect("ifort")

# Local Variables:
# tab-width:4
# indent-tabs-mode:nil
# End:
# vim: set expandtab tabstop=4 shiftwidth=4:
