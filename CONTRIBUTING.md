<!--
SPDX-FileCopyrightText: 2026 Federico T. Begna
SPDX-License-Identifier: MIT OR Apache-2.0
-->

# Contributing

## Prepare and choose a change

Obtain access while this repository is private, clone it, and follow [DEVELOPMENT](DEVELOPMENT.md) to install dependencies, build the compiler and run `examples/hola.omni`. Explore the [capability catalog](docs/language/CAPABILITY_STATUS.md) and [compiler map](compiler/README.md) to find the relevant implementation and tests. Small diagnostic, example, documentation and regression fixes are useful starting points.

```sh
git switch -c fix/describe-the-problem
python3 -B tools/check_local.py --scope tools
```

Preserve other work in your checkout. Write a regression that fails for the concrete defect, make the smallest coherent correction, and run the relevant [MATRIX](tests/MATRIX.json) group. Language changes need reviewed contracts and positive/negative behavior tests; normative reference is [spec/README.md](spec/README.md). ABI and format identities remain independent of product version.

## Validate and propose

Use `bash tools/ci.sh` for integrated Linux acceptance; `python -B tools/check_local.py` runs that same entry from PowerShell through WSL. Tooling-only feedback can use `--scope tools`; native changes need the affected functional checks. Documentation changes require working links and newly changed executable examples, not every historical test. Reports must identify commands, actual cases, skips and limits.

```sh
git add PATHS_YOU_CHANGED
git diff --cached
git commit -s -m "Describe the resulting behavior"
git push -u origin HEAD
```

Open a pull request from your branch to `main` using the [PR template](.github/PULL_REQUEST_TEMPLATE.md). Describe the problem, new behavior, contract implications and actual validation. Maintainers review admission; merging and publishing require separate authority. External PR workflows receive read-only permissions and no project secrets.

## Style, rights and responsibility

Use four-space Python indentation, descriptive names and focused functions for modified tools. Follow surrounding C/C++ conventions; keep unrelated dense code and golden fixtures untouched. See [maintenance boundaries](docs/architecture/MAINTAINABILITY.md).

Eligible contributions use MIT OR Apache-2.0. Preserve source attribution and third-party notices; contributors retain their rights. Read the [Developer Certificate of Origin 1.1](https://developercertificate.org/) and use your genuine `Signed-off-by` (`git commit -s`). DCO is distinct from a cryptographic signature; no initial CLA is required. AI-assisted work remains under the submitter's legal and technical responsibility.

Federico T. Begna (@sirfederick) is the initial maintainer. Follow [governance](GOVERNANCE.md), [conduct](CODE_OF_CONDUCT.md) and [security](SECURITY.md). Keep credentials, private application data and operational mandates out of the product.
