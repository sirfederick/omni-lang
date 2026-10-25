#!/usr/bin/env python3
"""Bounded Omni LSP 3.17 stdio server for the A87 profile."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.parse
from dataclasses import dataclass
from typing import Any, BinaryIO

MAX_MESSAGE = 1024 * 1024
MAX_FILE = 1024 * 1024
MAX_FILES = 256
MAX_RESULTS = 2048
IDENT = re.compile(r"[^\W\d]\w*", re.UNICODE)
DECL = re.compile(r"\b(?:module|func|record|enum|trait|let|var|const)\s+([^\W\d]\w*)", re.UNICODE)
KEYWORDS = (
    "module", "import", "func", "record", "enum", "trait", "impl", "let",
    "var", "return", "if", "else", "while", "for", "match", "true", "false",
)


class ProtocolError(Exception):
    pass


@dataclass
class Document:
    uri: str
    path: pathlib.Path
    text: str
    version: int


def contains(root: pathlib.Path, candidate: pathlib.Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def uri_path(uri: str, root: pathlib.Path) -> pathlib.Path:
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
        raise ProtocolError("only local file URIs are admitted")
    path = pathlib.Path(urllib.parse.unquote(parsed.path)).resolve()
    if not contains(root, path):
        raise ProtocolError("document is outside the admitted workspace")
    return path


def path_uri(path: pathlib.Path) -> str:
    return path.resolve().as_uri()


def lsp_character_to_index(line: str, character: int) -> int:
    if character < 0:
        raise ProtocolError("negative character offset")
    units = 0
    for index, value in enumerate(line):
        width = 2 if ord(value) > 0xFFFF else 1
        if units == character:
            return index
        if units + width > character:
            raise ProtocolError("position splits a UTF-16 surrogate pair")
        units += width
    if units == character:
        return len(line)
    raise ProtocolError("position exceeds line")


def word_at(text: str, position: dict[str, Any]) -> str:
    lines = text.splitlines()
    line_no = position.get("line")
    character = position.get("character")
    if not isinstance(line_no, int) or not isinstance(character, int) or not 0 <= line_no < len(lines):
        raise ProtocolError("invalid document position")
    line = lines[line_no]
    index = lsp_character_to_index(line, character)
    for match in IDENT.finditer(line):
        if match.start() <= index <= match.end():
            return match.group(0)
    raise ProtocolError("no symbol at position")


def location(uri: str, text: str, start: int, end: int) -> dict[str, Any]:
    before = text[:start]
    line = before.count("\n")
    line_start = before.rfind("\n") + 1
    start_character = len(before[line_start:].encode("utf-16-le")) // 2
    end_character = start_character + len(text[start:end].encode("utf-16-le")) // 2
    return {"uri": uri, "range": {"start": {"line": line, "character": start_character},
                                    "end": {"line": line, "character": end_character}}}


class Server:
    def __init__(self, compiler: pathlib.Path, workspace: pathlib.Path, output: BinaryIO) -> None:
        self.compiler = compiler.resolve()
        self.sdk_root = pathlib.Path(__file__).resolve().parents[1]
        self.version = (self.sdk_root / "VERSION").read_text(encoding="utf-8").strip()
        self.workspace = workspace.resolve()
        self.output = output
        self.documents: dict[str, Document] = {}
        self.shutdown = False

    def send(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self.output.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
        self.output.flush()

    def response(self, request_id: Any, result: Any) -> None:
        self.send({"jsonrpc": "2.0", "id": request_id, "result": result})

    def error(self, request_id: Any, code: int, message: str) -> None:
        self.send({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})

    def notify(self, method: str, params: Any) -> None:
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    def document(self, params: dict[str, Any]) -> Document:
        uri = params.get("textDocument", {}).get("uri")
        if not isinstance(uri, str) or uri not in self.documents:
            raise ProtocolError("document is not open")
        document = self.documents[uri]
        version = params.get("textDocument", {}).get("version")
        if version is not None and (type(version) is not int or version != document.version):
            raise ProtocolError("stale document version")
        return document

    def sources(self) -> dict[str, str]:
        result = {uri: document.text for uri, document in self.documents.items()}
        if len(result) > MAX_FILES:
            raise ProtocolError("workspace exceeds analysis file limit")
        for path in sorted(self.workspace.rglob("*.omni")):
            if path.is_symlink() or not path.is_file():
                continue
            resolved = path.resolve()
            if not contains(self.workspace, resolved):
                continue
            uri = path_uri(resolved)
            if uri in result:
                continue
            if len(result) >= MAX_FILES:
                raise ProtocolError("workspace exceeds analysis file limit")
            try:
                data = resolved.read_bytes()
                if len(data) > MAX_FILE:
                    raise ProtocolError("workspace file exceeds analysis limit")
                result[uri] = data.decode("utf-8")
            except (OSError, UnicodeDecodeError) as error:
                raise ProtocolError("workspace source cannot be analyzed") from error
        return result

    def package_metadata(self, texts: dict[str, str]) -> dict[pathlib.Path, bytes]:
        """Retain package commitments exactly; never relock a snapshot."""
        paths = set()
        for uri in texts:
            directory = uri_path(uri, self.workspace).parent
            while contains(self.workspace, directory):
                for name in ("omni.package.json", "omni.lock.json"):
                    path = directory / name
                    if path.is_symlink():
                        raise ProtocolError("package metadata symlink is not admitted")
                    if path.exists():
                        paths.add(path)
                if directory == self.workspace:
                    break
                directory = directory.parent
        if len(paths) > MAX_FILES:
            raise ProtocolError("package metadata exceeds analysis file limit")
        result = {}
        try:
            for path in sorted(paths):
                if not path.is_file() or path.stat().st_size > MAX_FILE:
                    raise ProtocolError("package metadata exceeds analysis limit")
                with path.open("rb") as source:
                    data = source.read(MAX_FILE + 1)
                if len(data) > MAX_FILE:
                    raise ProtocolError("package metadata exceeds analysis limit")
                result[path] = data
        except OSError as error:
            raise ProtocolError("package metadata cannot be analyzed") from error
        for path, data in result.items():
            if path.name != "omni.package.json":
                continue
            try:
                manifest = json.loads(data)
            except (ValueError, UnicodeError):
                continue  # the ordinary checker diagnoses malformed manifests
            dependencies = manifest.get("dependencies") if isinstance(manifest, dict) else None
            if not isinstance(dependencies, dict):
                continue
            for dependency in dependencies.values():
                relative = dependency.get("path") if isinstance(dependency, dict) else None
                if not isinstance(relative, str):
                    continue
                declared = path.parent / relative
                if any(part.is_symlink() for part in (declared, *declared.parents)):
                    raise ProtocolError("dependency symlink is not admitted")
                if declared.exists() or declared.is_symlink():
                    if declared.is_symlink() or not contains(self.workspace, declared.resolve()):
                        # Omitting an existing outside dependency could wrongly
                        # select bundled stdlib in the temporary snapshot.
                        raise ProtocolError("dependency is outside the admitted workspace")
        return result

    def write_metadata(self, root: pathlib.Path, metadata: dict[pathlib.Path, bytes]) -> None:
        for path, data in metadata.items():
            destination = root / path.relative_to(self.workspace)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)

    def checked_bindings(self, texts: dict[str, str]) -> tuple[list[dict[str, Any]], bool, dict[pathlib.Path, bytes]]:
        """Resolve with the real checker over one immutable workspace snapshot."""
        found: dict[tuple[Any, ...], dict[str, Any]] = {}
        complete = True
        metadata = self.package_metadata(texts)
        with tempfile.TemporaryDirectory(prefix="omni-lsp-bindings-") as temporary:
            root = pathlib.Path(temporary)
            self.write_metadata(root, metadata)
            for uri, text in texts.items():
                destination = root / uri_path(uri, self.workspace).relative_to(self.workspace)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(text, encoding="utf-8", newline="")
            for uri in sorted(texts):
                source = root / uri_path(uri, self.workspace).relative_to(self.workspace)
                try:
                    done = subprocess.run([str(self.compiler), "check", str(source), "--bindings-json"],
                                          capture_output=True, timeout=5,
                                          env={**os.environ, "OMNI_HOME": str(self.sdk_root)})
                    if done.returncode:
                        complete = False
                        continue
                    report = json.loads(done.stdout)
                    if report.get("schema") != "omni.bindings/1" or report.get("coordinate") != "utf8-byte-1-based":
                        raise ProtocolError("unsupported compiler binding report")
                    complete = complete and report.get("complete") is True
                    rows = []
                    for item in report["occurrences"]:
                        relative = pathlib.Path(item["source"]).resolve().relative_to(root.resolve())
                        target_uri = path_uri(self.workspace / relative)
                        text = texts[target_uri]
                        lines = text.splitlines(keepends=True)
                        line = int(item["line"]) - 1
                        column = int(item["column"]) - 1
                        raw = lines[line].encode("utf-8")
                        prefix = raw[:column].decode("utf-8")
                        name = raw[column:column + int(item["length"])].decode("utf-8")
                        if name != item["name"]:
                            raise ProtocolError("binding token does not match snapshot")
                        start = sum(map(len, lines[:line])) + len(prefix)
                        rows.append({**item, "uri": target_uri, "start": start, "end": start + len(name)})
                    declarations = {row["symbol"]: (row["uri"], row["start"], row["end"])
                                    for row in rows if row["role"] == "declaration"}
                    for row in rows:
                        if row["symbol"] not in declarations:
                            complete = False
                            continue
                        row["binding"] = declarations[row["symbol"]]
                        key = (row["uri"], row["start"], row["end"], row["binding"], row["role"])
                        found[key] = row
                        if len(found) > MAX_RESULTS:
                            raise ProtocolError("binding result limit exceeded")
                except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, IndexError, TypeError) as error:
                    raise ProtocolError("compiler binding analysis unavailable") from error
        if self.package_metadata(texts) != metadata:
            raise ProtocolError("package metadata changed during analysis")
        return sorted(found.values(), key=lambda row: (row["uri"], row["start"], row["role"])), complete, metadata

    def selected_binding(self, document: Document, position: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
        lines = document.text.splitlines(keepends=True)
        line, character = position.get("line"), position.get("character")
        if type(line) is not int or type(character) is not int or not 0 <= line < len(lines):
            raise ProtocolError("invalid document position")
        offset = sum(map(len, lines[:line])) + lsp_character_to_index(lines[line].rstrip("\r\n"), character)
        matches = [row for row in rows if row["uri"] == document.uri and row["start"] <= offset < row["end"]]
        if not matches or len({row["binding"] for row in matches}) != 1:
            raise ProtocolError("no unambiguous checked binding at position")
        return matches[0]

    def rename(self, document: Document, selected: dict[str, Any], new_name: Any,
               rows: list[dict[str, Any]], complete: bool, texts: dict[str, str],
               metadata: dict[pathlib.Path, bytes]) -> dict[str, Any]:
        if not isinstance(new_name, str) or re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,127}", new_name) is None:
            raise ProtocolError("invalid Omni identifier")
        if not complete:
            raise ProtocolError("rename requires a complete checked source mapping")
        edits: dict[str, list[tuple[int, int]]] = {}
        for row in rows:
            if row["binding"] == selected["binding"]:
                edits.setdefault(row["uri"], []).append((row["start"], row["end"]))
        changed = dict(texts)
        for uri, spans in edits.items():
            for start, end in sorted(set(spans), reverse=True):
                changed[uri] = changed[uri][:start] + new_name + changed[uri][end:]
        after, accepted, after_metadata = self.checked_bindings(changed)
        if not accepted:
            raise ProtocolError("rename creates a conflict or invalid program")

        def mapped(uri: str, start: int, end: int) -> tuple[str, int, int]:
            spans = set(edits.get(uri, []))
            delta = sum(len(new_name) - (b - a) for a, b in spans if a < start)
            width = len(new_name) if (start, end) in spans else end - start
            return uri, start + delta, start + delta + width

        expected = {(mapped(row["uri"], row["start"], row["end"]), mapped(*row["binding"]), row["role"]) for row in rows}
        actual = {((row["uri"], row["start"], row["end"]), row["binding"], row["role"]) for row in after}
        if actual != expected:
            raise ProtocolError("rename would capture or change another binding")
        if self.sources() != texts or after_metadata != metadata or self.package_metadata(texts) != metadata:
            raise ProtocolError("workspace changed during rename analysis")
        return {"documentChanges": [
            {"textDocument": {"uri": uri, "version": self.documents[uri].version if uri in self.documents else None},
             "edits": [{"range": location(uri, texts[uri], start, end)["range"], "newText": new_name}
                       for start, end in sorted(set(spans))]}
            for uri, spans in sorted(edits.items())]}

    def snapshot(self, root: pathlib.Path, document: Document) -> pathlib.Path:
        """Write the admitted workspace view (open buffers over disk) so relative imports resolve."""
        views = {}
        for uri, text in self.sources().items():
            try:
                views[uri_path(uri, self.workspace)] = text
            except ProtocolError:
                continue
        views.update({open_document.path: open_document.text for open_document in self.documents.values()})
        views[document.path] = document.text
        self.write_metadata(root, self.package_metadata({path_uri(path): text for path, text in views.items()}))
        target = root / document.path.name
        for path, text in views.items():
            destination = root / path.relative_to(self.workspace)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(text, encoding="utf-8", newline="")
            if path == document.path:
                target = destination
        return target

    def related_information(self, item: dict[str, Any], root: pathlib.Path, source: pathlib.Path,
                            document: Document) -> list[dict[str, Any]]:
        """Map the compiler's optional `related` locations (snapshot paths) to LSP relatedInformation (workspace URIs)."""
        result: list[dict[str, Any]] = []
        for entry in (item.get("related") or [])[:8]:
            try:
                where = pathlib.Path(str(entry["source"])).resolve()
                real = self.workspace / where.relative_to(root.resolve())
                text = document.text if where == source.resolve() else where.read_text(encoding="utf-8")
                span = entry["span"]
                line = max(0, int(span["line"]) - 1)
                column = max(0, int(span["column"]) - 1)
                lines = text.split("\n")
                content = lines[line] if line < len(lines) else ""
                start = len(content[:column].encode("utf-16-le", "surrogatepass")) // 2
                width = len(content[column:column + 1].encode("utf-16-le", "surrogatepass")) // 2 or 1
                result.append({"location": {"uri": path_uri(real),
                                            "range": {"start": {"line": line, "character": start},
                                                      "end": {"line": line, "character": start + width}}},
                               "message": str(entry.get("note", entry.get("role", "related")))[:1024]})
            except (KeyError, ValueError, TypeError, OSError, UnicodeDecodeError):
                continue
        return result

    def diagnostics(self, document: Document) -> list[dict[str, Any]]:
        if len(document.text.encode("utf-8")) > MAX_FILE:
            return [{"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
                     "severity": 1, "code": "E_LIMIT", "source": "omni",
                     "message": "document exceeds the A87 analysis limit"}]
        with tempfile.TemporaryDirectory(prefix="omni-lsp-") as temporary:
            source = self.snapshot(pathlib.Path(temporary), document)
            env ={**os.environ, "OMNI_HOME": str(self.sdk_root), "PYTHONDONTWRITEBYTECODE": "1"}
            try:
                result = subprocess.run(
                    [str(self.compiler), "check", str(source), "--diagnostic-format", "json"],
                    capture_output=True, timeout=5, env=env, check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                return [{"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
                         "severity": 1, "code": "E_TOOL", "source": "omni",
                         "message": "bounded compiler analysis unavailable"}]
            if result.returncode == 0:
                return []
            try:
                item = json.loads(result.stderr.decode("utf-8"))
                message = str(item.get("message", "analysis failed"))
                reported = item.get("source")
                if reported and pathlib.Path(reported).resolve() != source.resolve():
                    # The failing file is an imported one: do not borrow its span for this document.
                    try:
                        origin = str(pathlib.Path(reported).resolve().relative_to(source.resolve().parent))
                    except ValueError:
                        origin = pathlib.Path(reported).name
                    return [{"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}},
                             "severity": 1, "code": str(item.get("code", "E_INTERNAL")),
                             "source": "omni", "message": f"{origin}: {message}"[:4096]}]
                span = item.get("span") or {"line": 1, "column": 1}
                line = max(0, int(span.get("line", 1)) - 1)
                column = max(0, int(span.get("column", 1)) - 1)
                start, width = column, 1
                if span.get("coordinate") == "unicode-scalar-1-based":
                    # The compiler counts Unicode scalars; LSP positions are UTF-16 code units.
                    lines = document.text.split("\n")
                    text = lines[line] if line < len(lines) else ""
                    start = len(text[:column].encode("utf-16-le", "surrogatepass")) // 2
                    width = len(text[column:column + 1].encode("utf-16-le", "surrogatepass")) // 2 or 1
                diagnostic = {"range": {"start": {"line": line, "character": start},
                                        "end": {"line": line, "character": start + width}},
                              "severity": 1, "code": str(item.get("code", "E_INTERNAL")),
                              "source": "omni", "message": message[:4096]}
                related = self.related_information(item, pathlib.Path(temporary), source, document)
                if related:
                    diagnostic["relatedInformation"] = related
                proposals = []
                for fix in (item.get("fixits") or [])[:8]:
                    try:
                        parsed = urllib.parse.urlparse(fix["source_uri"])
                        if parsed.scheme != "file" or pathlib.Path(urllib.parse.unquote(parsed.path)).resolve() != source.resolve():
                            continue
                        if fix.get("coordinate") != "utf8-byte-1-based":
                            continue
                        lines = document.text.splitlines(keepends=True)
                        line, column = int(fix["line"]) - 1, int(fix["column"]) - 1
                        if line < 0 or column < 0:
                            continue
                        start = sum(map(len, lines[:line])) + len(lines[line].encode("utf-8")[:column].decode("utf-8"))
                        expected, replacement = fix["expected"], fix["replacement"]
                        if not isinstance(expected, str) or not isinstance(replacement, str) or not expected:
                            continue
                        if document.text[start:start + len(expected)] != expected:
                            continue
                        proposals.append({"range": location(document.uri, document.text, start, start + len(expected))["range"],
                                          "newText": replacement, "expected": expected})
                    except (KeyError, ValueError, TypeError, IndexError, UnicodeError):
                        continue
                if proposals:
                    diagnostic["data"] = {"fixits": proposals, "version": document.version}
                return [diagnostic]
            except (ValueError, UnicodeDecodeError, TypeError):
                return [{"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
                         "severity": 1, "code": "E_INTERNAL", "source": "omni",
                         "message": "compiler returned a malformed diagnostic"}]

    def publish(self, document: Document) -> None:
        self.notify("textDocument/publishDiagnostics", {
            "uri": document.uri, "version": document.version,
            "diagnostics": self.diagnostics(document),
        })

    def handle(self, message: dict[str, Any]) -> bool:
        request_id = message.get("id")
        method = message.get("method")
        params = message.get("params") or {}
        if not isinstance(method, str) or not isinstance(params, dict):
            if "id" in message:
                self.error(request_id, -32600, "invalid request")
            return True
        try:
            if method.startswith("textDocument/") and not isinstance(params.get("textDocument"), dict):
                raise ProtocolError("malformed textDocument object")
            if method in ("textDocument/hover", "textDocument/definition", "textDocument/references", "textDocument/rename") and not isinstance(params.get("position"), dict):
                raise ProtocolError("malformed document position")
            if method == "textDocument/references" and not isinstance(params.get("context", {}), dict):
                raise ProtocolError("malformed references context")
            if method == "initialize":
                self.response(request_id, {"serverInfo": {"name": "omni-lsp", "version": self.version},
                    "capabilities": {"textDocumentSync": 1, "completionProvider": {"triggerCharacters": ["."]},
                    "hoverProvider": True, "definitionProvider": True, "referencesProvider": True,
                    "renameProvider": {"prepareProvider": False}, "codeActionProvider": True, "positionEncoding": "utf-16"}})
            elif method == "initialized":
                pass
            elif method == "shutdown":
                self.shutdown = True
                self.response(request_id, None)
            elif method == "exit":
                return False
            elif self.shutdown:
                if "id" in message:
                    self.error(request_id, -32600, "server is shut down")
            elif method == "textDocument/didOpen":
                item = params.get("textDocument", {})
                uri, text, version = item.get("uri"), item.get("text"), item.get("version")
                if not isinstance(uri, str) or not isinstance(text, str) or type(version) is not int:
                    raise ProtocolError("malformed didOpen")
                if uri in self.documents:
                    raise ProtocolError("document is already open")
                path = uri_path(uri, self.workspace)
                if len(text.encode("utf-8")) > MAX_FILE:
                    raise ProtocolError("document exceeds analysis limit")
                document = Document(uri, path, text, version)
                self.documents[uri] = document
                self.publish(document)
            elif method == "textDocument/didChange":
                # didChange carries the NEW version, not the snapshot version.
                document = self.document({"textDocument": {"uri": params.get("textDocument", {}).get("uri")}})
                version = params.get("textDocument", {}).get("version")
                changes = params.get("contentChanges")
                if type(version) is not int or version <= document.version:
                    raise ProtocolError("stale document version")
                if not isinstance(changes, list) or len(changes) != 1 or not isinstance(changes[0], dict) or not isinstance(changes[0].get("text"), str):
                    raise ProtocolError("A87 requires one full-content change")
                if "range" in changes[0] or "rangeLength" in changes[0]:
                    raise ProtocolError("full-content synchronization does not accept ranged edits")
                text = changes[0]["text"]
                if len(text.encode("utf-8")) > MAX_FILE:
                    raise ProtocolError("document exceeds analysis limit")
                document.text, document.version = text, version
                self.publish(document)
            elif method == "textDocument/didClose":
                document = self.document(params)
                del self.documents[document.uri]
                self.notify("textDocument/publishDiagnostics", {"uri": document.uri, "diagnostics": []})
            elif method == "textDocument/completion":
                document = self.document(params)
                names = set(KEYWORDS)
                for text in self.sources().values():
                    names.update(match.group(1) for match in DECL.finditer(text))
                self.response(request_id, {"isIncomplete": False, "items": [
                    {"label": name, "kind": 14 if name in KEYWORDS else 6} for name in sorted(names)[:MAX_RESULTS]
                ]})
            elif method == "textDocument/codeAction":
                document = self.document(params)
                actions = []
                # Recompute from the current snapshot; context supplied by a
                # client cannot manufacture an edit or reuse a stale fix-it.
                for diagnostic in self.diagnostics(document):
                    for fix in diagnostic.get("data", {}).get("fixits", []):
                        actions.append({"title": f"Replace {fix['expected']} with {fix['newText']}", "kind": "quickfix",
                                        "diagnostics": [diagnostic], "edit": {"documentChanges": [{
                                            "textDocument": {"uri": document.uri, "version": document.version},
                                            "edits": [{"range": fix["range"], "newText": fix["newText"]}]}]}})
                self.response(request_id, actions)
            elif method in ("textDocument/hover", "textDocument/definition", "textDocument/references", "textDocument/rename"):
                document = self.document(params)
                texts = self.sources()
                rows, complete, metadata = self.checked_bindings(texts)
                selected = self.selected_binding(document, params.get("position", {}), rows)
                if method == "textDocument/references" and not complete:
                    raise ProtocolError("references require a complete checked source mapping")
                refs = [row for row in rows if row["binding"] == selected["binding"]]
                declarations = [location(row["uri"], texts[row["uri"]], row["start"], row["end"])
                                for row in refs if row["role"] == "declaration"]
                if method == "textDocument/hover":
                    value = f"`{selected['name']}` — Omni symbol (checked binding)"
                    self.response(request_id, {"contents": {"kind": "markdown", "value": value}})
                elif method == "textDocument/definition":
                    self.response(request_id, declarations[:1] or None)
                elif method == "textDocument/references":
                    include = params.get("context", {}).get("includeDeclaration", True)
                    self.response(request_id, [location(row["uri"], texts[row["uri"]], row["start"], row["end"])
                                               for row in refs if include or row["role"] != "declaration"])
                else:
                    self.response(request_id, self.rename(document, selected, params.get("newName"), rows, complete, texts, metadata))
            else:
                if "id" in message:
                    self.error(request_id, -32601, "method not found")
        except (ProtocolError, UnicodeError) as error:
            if "id" in message:
                self.error(request_id, -32001, str(error))
            else:
                self.notify("window/logMessage", {"type": 2, "message": str(error)})
        return True


def read_message(stream: BinaryIO) -> dict[str, Any] | None:
    headers: dict[bytes, bytes] = {}
    while True:
        line = stream.readline(MAX_MESSAGE + 1)
        if not line:
            return None
        if len(line) > MAX_MESSAGE:
            raise ProtocolError("oversized LSP header")
        if line in (b"\r\n", b"\n"):
            break
        if b":" not in line:
            raise ProtocolError("malformed LSP header")
        name, value = line.split(b":", 1)
        headers[name.strip().lower()] = value.strip()
    raw_length = headers.get(b"content-length")
    if raw_length is None or not raw_length.isdigit():
        raise ProtocolError("missing Content-Length")
    length = int(raw_length)
    if length > MAX_MESSAGE:
        raise ProtocolError("oversized LSP message")
    body = stream.read(length)
    if len(body) != length:
        raise ProtocolError("truncated LSP message")
    message = json.loads(body.decode("utf-8"))
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        raise ProtocolError("invalid JSON-RPC envelope")
    return message


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiler", required=True, type=pathlib.Path)
    parser.add_argument("--workspace", required=True, type=pathlib.Path)
    args = parser.parse_args()
    compiler, workspace = args.compiler.resolve(), args.workspace.resolve()
    if not compiler.is_file() or not workspace.is_dir() or workspace.is_symlink():
        return 2
    server = Server(compiler, workspace, sys.stdout.buffer)
    try:
        while True:
            message = read_message(sys.stdin.buffer)
            if message is None:
                return 0 if server.shutdown else 2
            if not server.handle(message):
                return 0 if server.shutdown else 2
    except (ProtocolError, UnicodeDecodeError, json.JSONDecodeError):
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
