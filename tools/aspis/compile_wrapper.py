#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-2-Clause
# Copyright (C) 2026 The RTEMS Project contributors

import argparse
import json
import os
import subprocess
import sys


def parse_invocation(argv):
    try:
        separator = argv.index("--")
    except ValueError:
        separator = len(argv)

    parser = argparse.ArgumentParser(description="ASPIS RTEMS compiler wrapper")
    parser.add_argument("--clang", required=True)
    parser.add_argument("--opt", required=True)
    parser.add_argument("--passes", required=True)
    config = parser.parse_args(argv[:separator])
    compiler_args = argv[separator + 1:] if separator < len(argv) else []
    return config, compiler_args


config, args = parse_invocation(sys.argv[1:])
CLANG = config.clang
OPT = config.opt
PASSES = config.passes

LINKED_SAMPLE = "/testsuites/samples/aspis_sample_hardened/"
RASM_TARGETS = ("timespecisvalid.c",)

src = next(
    (a for a in args if a.endswith(".c") and not a.startswith("-")),
    None,
)

def fail(message):
    print(f"[aspis-cc] Error: {message}", file=sys.stderr)
    sys.exit(1)

def run_cmd(cmd, cwd=None):
    try:
        subprocess.run(cmd, check=True, cwd=cwd)
    except (OSError, subprocess.CalledProcessError) as error:
        print(
            f"[aspis-cc] Command failed: {' '.join(cmd)}: {error}",
            file=sys.stderr,
        )
        sys.exit(getattr(error, "returncode", 1))

def parse_compile_args(argv, source):
    out = None
    flags = []
    skip_next = False

    for index, arg in enumerate(argv):
        if skip_next:
            skip_next = False
            continue
        if arg in ("-c", "-S"):
            continue
        if arg == "-o":
            if index + 1 >= len(argv):
                fail("missing argument after -o")
            out = argv[index + 1]
            skip_next = True
            continue
        if arg.startswith("-o") and len(arg) > 2:
            out = arg[2:]
            continue
        if arg in ("-MF", "-MT", "-MQ", "-MJ"):
            skip_next = True
            continue
        if arg in ("-MMD", "-MD", "-MP", "-MG"):
            continue
        if arg == source:
            continue
        flags.append(arg)

    return out, flags

normalized_src = (
    "/" + os.path.abspath(src).replace(os.sep, "/").lstrip("/")
    if src
    else ""
)

if src and LINKED_SAMPLE in normalized_src:
    out, backend_flags = parse_compile_args(args, src)
    if not out:
        fail("output flag (-o) not found")

    # Keep Waf's declared output as a native object and exchange a separate,
    # explicitly textual LLVM IR sidecar with the ASPIS link wrapper.
    run_cmd([CLANG] + args)
    absolute_output = os.path.abspath(out)
    llvm_ir = absolute_output + ".aspis.ll"
    temporary_ir = f"{llvm_ir}.tmp.{os.getpid()}"
    run_cmd(
        [CLANG]
        + backend_flags
        + ["-emit-llvm", "-S", src, "-o", temporary_ir]
    )
    os.replace(temporary_ir, llvm_ir)

    manifest = {
        "format": 1,
        "source": os.path.abspath(src),
        "object": absolute_output,
        "llvm_ir": llvm_ir,
        "llvm_ir_format": "text",
        "backend_flags": backend_flags,
    }
    manifest_path = absolute_output + ".aspis.json"
    temporary_manifest = f"{manifest_path}.tmp.{os.getpid()}"
    with open(temporary_manifest, "w", encoding="utf-8") as output:
        json.dump(manifest, output, indent=2)
        output.write(chr(10))
    os.replace(temporary_manifest, manifest_path)

    print(f"[aspis-cc] TEXTUAL LLVM IR {src} -> {llvm_ir}", file=sys.stderr)
    sys.exit(0)

needs_rasm = src and any(target in normalized_src for target in RASM_TARGETS)
if not needs_rasm:
    os.execv(CLANG, [CLANG] + args)

out, flags = parse_compile_args(args, src)
if not out:
    fail("output flag (-o) not found")

depfile = os.path.splitext(out)[0] + ".d"
debug_dir = os.path.abspath(out) + ".aspis"
os.makedirs(debug_dir, exist_ok=True)

raw_ir = os.path.join(debug_dir, "00-source.ll")
lowered_ir = os.path.join(debug_dir, "01-lower-switch.ll")
simplified_ir = os.path.join(debug_dir, "02-simplifycfg.ll")
rasm_ir = os.path.join(debug_dir, "03-rasm.ll")

run_cmd(
    [CLANG]
    + flags
    + ["-g", "-MMD", "-MF", depfile, "-emit-llvm", "-S", src, "-o", raw_ir]
)
run_cmd(
    [OPT, "-passes=lower-switch", raw_ir, "-o", lowered_ir, "-S"],
    cwd=debug_dir,
)
run_cmd(
    [OPT, "-passes=simplifycfg", lowered_ir, "-o", simplified_ir, "-S"],
    cwd=debug_dir,
)
run_cmd(
    [
        OPT,
        "-load-pass-plugin",
        os.path.join(PASSES, "libRASM.so"),
        "-debug-enabled=true",
        "-passes=rasm-verify",
        simplified_ir,
        "-o",
        rasm_ir,
        "-S",
    ],
    cwd=debug_dir,
)
run_cmd([CLANG] + flags + ["-c", rasm_ir, "-o", out])

print(
    f"[aspis-cc] RASM {src} -> {out} (IR saved in {debug_dir})",
    file=sys.stderr,
)
