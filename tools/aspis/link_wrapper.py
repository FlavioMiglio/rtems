#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-2-Clause
# Copyright (C) 2026 The RTEMS Project contributors

import argparse
import json
import os
import re
import subprocess
import sys


def parse_invocation(argv):
    try:
        separator = argv.index("--")
    except ValueError:
        separator = len(argv)

    parser = argparse.ArgumentParser(description="ASPIS RTEMS link wrapper")
    parser.add_argument("--clang", required=True)
    parser.add_argument("--opt", required=True)
    parser.add_argument("--llvm-link", required=True)
    parser.add_argument("--gcc", required=True)
    parser.add_argument("--passes", required=True)
    config = parser.parse_args(argv[:separator])
    linker_args = argv[separator + 1:] if separator < len(argv) else []
    return config, linker_args


config, args = parse_invocation(sys.argv[1:])
CLANG = config.clang
OPT = config.opt
LLVM_LINK = config.llvm_link
GCC = config.gcc
PASSES = config.passes

TARGET_SUFFIX = "/testsuites/samples/aspis_sample_hardened.exe"
GROUP_MARKER = "/testsuites/samples/aspis_sample_hardened/"
EXPECTED_SOURCES = ("workload.c", "apptask.c", "init.c")

def fail(message):
    print(f"[aspis-link] Errore: {message}", file=sys.stderr)
    sys.exit(1)

def run_cmd(cmd, cwd=None):
    try:
        subprocess.run(cmd, check=True, cwd=cwd)
    except (OSError, subprocess.CalledProcessError) as error:
        print(
            f"[aspis-link] Errore comando: {' '.join(cmd)}: {error}",
            file=sys.stderr,
        )
        sys.exit(getattr(error, "returncode", 1))

def find_output(argv):
    for index, arg in enumerate(argv):
        if arg == "-o":
            if index + 1 >= len(argv):
                fail("argomento mancante dopo -o")
            return argv[index + 1]
        if arg.startswith("-o") and len(arg) > 2:
            return arg[2:]
    return None

def normalized(path):
    return "/" + os.path.abspath(path).replace(os.sep, "/").lstrip("/")

output = find_output(args)
if not output or not normalized(output).endswith(TARGET_SUFFIX):
    os.execvp(GCC, [GCC] + args)

group_objects = [
    arg
    for arg in args
    if arg.endswith(".o") and GROUP_MARKER in normalized(arg)
]

matched = {}
for object_path in group_objects:
    object_name = os.path.basename(object_path)
    for source_name in EXPECTED_SOURCES:
        if object_name.startswith(source_name + "."):
            if source_name in matched:
                fail(f"input duplicato per {source_name}")
            matched[source_name] = object_path
            break

missing = [name for name in EXPECTED_SOURCES if name not in matched]
if missing or len(group_objects) != len(EXPECTED_SOURCES):
    fail(
        "set di bitcode incompleto: "
        f"attesi {EXPECTED_SOURCES}, trovati {group_objects}, mancanti {missing}"
    )

manifests = []
absolute_objects = []
for source_name in EXPECTED_SOURCES:
    object_path = os.path.abspath(matched[source_name])
    absolute_objects.append(object_path)

    try:
        with open(object_path, "rb") as bitcode:
            magic = bitcode.read(4)
    except OSError as error:
        fail(f"impossibile leggere {object_path}: {error}")
    if magic not in (b"BC\xc0\xde", b"\xde\xc0\x17\x0b"):
        fail(f"{object_path} non contiene LLVM bitcode")

    manifest_path = object_path + ".aspis.json"
    try:
        with open(manifest_path, "r", encoding="utf-8") as manifest_file:
            manifests.append(json.load(manifest_file))
    except (OSError, ValueError) as error:
        fail(f"manifest non valido {manifest_path}: {error}")

backend_flags = manifests[0].get("backend_flags")
if not isinstance(backend_flags, list):
    fail("backend_flags assenti dal manifest")
if any(manifest.get("backend_flags") != backend_flags for manifest in manifests[1:]):
    fail("i translation unit usano flag di code generation incompatibili")

debug_dir = os.path.abspath(output) + ".aspis"
os.makedirs(debug_dir, exist_ok=True)

linked_ir = os.path.join(debug_dir, "00-linked.ll")
lowered_ir = os.path.join(debug_dir, "01-lower-switch.ll")
func_ret_ir = os.path.join(debug_dir, "02-func-ret.ll")
line_table_ir = os.path.join(debug_dir, "02-line-tables.ll")
seddi_ir = os.path.join(debug_dir, "03-seddi.ll")
simplified_ir = os.path.join(debug_dir, "04-simplifycfg.ll")
rasm_ir = os.path.join(debug_dir, "05-rasm.ll")
final_ir = os.path.join(debug_dir, "06-globals.ll")
combined_object = os.path.join(debug_dir, "aspis_sample_hardened.o")

with open(os.path.join(debug_dir, "inputs.json"), "w", encoding="utf-8") as info:
    json.dump(
        {
            "objects": absolute_objects,
            "sources": [manifest.get("source") for manifest in manifests],
            "backend_flags": backend_flags,
        },
        info,
        indent=2,
    )
    info.write(chr(10))

run_cmd(
    [LLVM_LINK, "-S"] + absolute_objects + ["-o", linked_ir],
    cwd=debug_dir,
)

try:
    with open(linked_ir, "r", encoding="utf-8") as linked_file:
        linked_text = linked_file.read()
except OSError as error:
    fail(f"impossibile verificare {linked_ir}: {error}")

required_definitions = (
    "main",
    "Init",
    "workload_run",
    "aspis_test_injection_point",
    "aspis_data_checkpoint",
    "DataCorruption_Handler",
    "SigMismatch_Handler",
)
missing_definitions = [
    name
    for name in required_definitions
    if not re.search(r"\bdefine\b[^\n]*@" + re.escape(name) + r"\(", linked_text)
]
if missing_definitions:
    fail(f"definizioni mancanti nel modulo collegato: {missing_definitions}")
if re.search(r"@Application_task\(", linked_text):
    fail("Application_task non e' stato esposto come entry point IR main")

run_cmd(
    [OPT, "-passes=lower-switch", linked_ir, "-o", lowered_ir, "-S"],
    cwd=debug_dir,
)
run_cmd(
    [
        OPT,
        "-load-pass-plugin",
        os.path.join(PASSES, "libEDDI.so"),
        "-debug-enabled=true",
        "-passes=func-ret-to-ref",
        lowered_ir,
        "-o",
        func_ret_ir,
        "-S",
    ],
    cwd=debug_dir,
)
run_cmd(
    [
        OPT,
        "-passes=strip-nonlinetable-debuginfo",
        func_ret_ir,
        "-o",
        line_table_ir,
        "-S",
    ],
    cwd=debug_dir,
)
run_cmd(
    [
        OPT,
        "-load-pass-plugin",
        os.path.join(PASSES, "libSEDDI.so"),
        "-debug-enabled=true",
        "-passes=eddi-verify",
        line_table_ir,
        "-o",
        seddi_ir,
        "-S",
    ],
    cwd=debug_dir,
)
run_cmd(
    [OPT, "-passes=simplifycfg", seddi_ir, "-o", simplified_ir, "-S"],
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
run_cmd(
    [
        OPT,
        "-load-pass-plugin",
        os.path.join(PASSES, "libEDDI.so"),
        "-debug-enabled=true",
        "-passes=duplicate-globals",
        rasm_ir,
        "-o",
        final_ir,
        "-S",
    ],
    cwd=debug_dir,
)

try:
    with open(final_ir, "r", encoding="utf-8") as final_file:
        final_text = final_file.read()
except OSError as error:
    fail(f"impossibile verificare {final_ir}: {error}")

if not re.search(r"\bdefine\b[^\n]*@main\(", final_text):
    fail("sEDDI non ha mantenuto l'entry point main")
if not re.search(r"@workload_run(?:_ret)?_dup\(", final_text):
    fail("sEDDI non ha generato il percorso duplicato del workload")
for checkpoint in ("aspis_test_injection_point", "aspis_data_checkpoint"):
    if not re.search(r"\bcall\b[^\n]*@" + checkpoint + r"\(", final_text):
        fail(f"checkpoint eliminato dalla pipeline: {checkpoint}")

run_cmd(
    [CLANG] + backend_flags + ["-Qunused-arguments", "-c", final_ir, "-o", combined_object]
)

replacement_args = []
inserted = False
group_set = set(group_objects)
for arg in args:
    if arg in group_set:
        if not inserted:
            replacement_args.append(combined_object)
            inserted = True
        continue
    replacement_args.append(arg)
if not inserted:
    fail("impossibile sostituire i bitcode nel comando di link")

print(
    f"[aspis-link] LINKED sEDDI/RASM -> {combined_object}; link finale {output}",
    file=sys.stderr,
)
os.execvp(GCC, [GCC] + replacement_args)
