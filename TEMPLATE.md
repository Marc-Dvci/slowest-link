# Using this template

This repository is the starting point for a competition project. It carries the boilerplate that
`D:\Context\DEVPOST_PROJECT_REQUIREMENTS.md` asks for, so a new project starts polished instead of being polished at
the end. Every piece is a means to win: keep what helps this project, and delete what doesn't.

## Start a project

```sh
gh repo create Marc-Dvci/<repo> --private --template Marc-Dvci/project-template --clone
cd <repo>
python scripts/init_project.py --name "<Name>" --repo <repo> --tagline "<what it does for whom>"
```

`init_project.py` fills `{{NAME}}`, `{{REPO}}`, `{{OWNER}}`, `{{YEAR}}` and `{{TAGLINE}}` everywhere, deletes this file
and itself, and lists the placeholders left for later (demo URL, video, sponsor, results date...).

## What is here, and where the rules come from

| Piece | Files | Rules section |
|---|---|---|
| README in the winning order, video thumbnail, badges, "For judges", claims table | `README.md`, `docs/film_thumbnail.jpg` | 4, 5 |
| Deterministic core with its tests, and an HTTP API that refuses cleanly without a key | `app/`, `tests/` | 2, 6 |
| Lint, format, types, tests in random order with timeouts, line and branch coverage of the core, spelling, local links | `pyproject.toml`, `tests/conftest.py`, `.github/workflows/tests.yml`, `scripts/check_links.py` | 5, 6 |
| Docker: `demo` (no keys, the default) and `app` (your keys), smoke-tested in CI | `Dockerfile`, `compose.yaml`, `.dockerignore` | 5 |
| Run it without installing | `.devcontainer/devcontainer.json` | 5 |
| CodeQL (runs once the repository is public) and a live smoke test (off until set) | `.github/workflows/codeql.yml`, `.github/workflows/live.yml` | 5 |
| A web page with a title, favicon and Open Graph card | `web/` | 3 |
| Architecture diagram as a committed image, and README GIFs | `docs/architecture.mmd`, `scripts/render_diagram.py`, `scripts/make_gif.py` | 4, 5 |
| Optional: security policy, correction form, citation, system card, sample outputs | `SECURITY.md`, `.github/ISSUE_TEMPLATE/`, `CITATION.cff`, `docs/SYSTEM_CARD.md`, `examples/` | 5 |

## Delete what doesn't help

- No server or web page: delete `app/server.py`, `web/`, `Dockerfile`, `compose.yaml`, `.dockerignore`,
  `.devcontainer/`, the `docker` job and `live.yml`.
- A React or Vite front end: replace `web/` with it; the `web` CI job turns on by itself once `web/package.json`
  exists. Add a Node build stage to the `Dockerfile`. If it has vitest tests, add
  `npx vitest run --coverage --sequence.shuffle` to that job.
- No public live endpoint, keys, money or personal data: delete `SECURITY.md`.
- No findings about real organisations or people: delete `.github/ISSUE_TEMPLATE/`.
- No evaluation, dataset or quotable result: delete `CITATION.cff`.
- No model output feeding a decision about people, money or compliance: delete `docs/SYSTEM_CARD.md`.
- No output a judge could open: delete `examples/`.

## Tests

- Unmarked tests count as unit tests. Mark a test that goes through an entry point (HTTP route, CLI, tool wrapper)
  `@pytest.mark.integration`, and a browser test `@pytest.mark.e2e`; the CI summary counts each kind.
- Tests run in a new random order on every run. CI uses its run number as the seed and prints it, so a red order can
  be replayed with `python -m pytest --randomly-seed=<run number>`.
- On CI, Hypothesis uses the derandomized `ci` profile in `tests/conftest.py`: the same commit runs the same examples.
- A skip or expected failure states its reason (`@pytest.mark.skip(reason="...")`); `-ra` prints every one, and an
  expected failure that starts passing fails the run.

## Placeholders

`{{...}}` marks a value to fill, and `TEMPLATE:` marks guidance to act on and then delete. CI lists both as warnings;
before submitting, this must print nothing and exit 0:

```sh
python scripts/check_placeholders.py --strict
```

## Keeping the template current

When the rules file changes, change this template the same way. It names no project: keep it generic.
