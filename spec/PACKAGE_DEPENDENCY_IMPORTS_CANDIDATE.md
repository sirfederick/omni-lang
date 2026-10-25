> Distribution status: WIP / NOT_RELEASED. Technical version labels describe independent contracts, not public release certification.

# CP-05 candidate — importing a module of a locked dependency package

Status: candidate for Core 1.3.0.0, amending `PACKAGES_STDLIB_0_8_4.md` (which deferred cross-package source imports) without changing it for programs that do not use the new form.
It answers row 5.10: a library in its own package is consumed by another package **without copying its source**, and the resources it owns stay owned.

## 1. The form

```omni
import seq "@acme.coll/seq.omni"
```

A path that starts with `@` is `@<dependency>/<relative path>.omni`. `<dependency>` is the key of an entry in `dependencies` of the manifest of the package that contains the
importing file (`omni.package.json` found by walking up from the file; the file must be under that package's `src/`). `<relative path>` is relative to the dependency's `src/`.
Any other path keeps its meaning: relative to the importing file and inside the package's own source tree.

## 2. What is checked, in this order (fail closed)

| Condition | Diagnostic |
|---|---|
| the importing file is under no package, or the dependency is not declared in its manifest | `E_IMPORT_PATH` |
| the path after the name is empty, absolute, or contains `..`/`.` components, or does not end in `.omni` | `E_IMPORT_PATH` |
| the lock is missing, or the manifest or the source of any package of the closure no longer matches `omni.lock.json` | `E_PACKAGE_LOCK` |
| the dependency cannot be resolved (path, version, cycle) | `E_PACKAGE_RESOLVE` / `E_PACKAGE_PATH` / `E_PACKAGE_CYCLE` |
| the resolved file is a symbolic link, or is not inside the dependency's `src/` | `E_IMPORT_PATH` |
| two files declare the same module name, wherever they come from | `E_DUPLICATE` |

The lock check is the one of `omni package check --offline`: no network, no registry, no scripts. The relative imports **inside** a dependency stay inside that dependency's `src/`
(they are resolved against the dependency, and its own `@` imports against its own manifest). The consumer's source is never copied: the loader reads the dependency where it is.

## 3. What it does not change

The module system is unchanged below the import: a module is one file, its name is global, visibility (`pub`) decides what the importer can use, and the generic, trait and
ownership rules apply across the package boundary exactly as across files of one package (`seq.Dispose`, `Resource<T>`, `destroy`). Particle, Wave, Wire and ONME are unchanged:
a program with imports is a bundle of its modules, and the identity of the artifact covers the bytes of every file that was read. The sources of a dependency enter the artifact by
being read from the locked package, not by being pasted into the consumer. No registry, no remote fetch, no version ranges, no publisher identity.

## 4. Evidence

`tests/cp05_packages.py`: a library package with an owning sequence consumed by an application package, evaluator and native binary agree and nothing of the library is in the application;
the elements are still linear across the boundary (`E_RESOURCE_UNCONSUMED` when the sequence is not destroyed); a dependency changed after the lock, a missing lock, an undeclared
dependency, a path that escapes, a file outside every package, a clashing module name, and the relative imports of a dependency.
