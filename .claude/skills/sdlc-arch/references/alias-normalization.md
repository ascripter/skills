# Alias normalization

User input — typed arguments, prose mentions in interview answers,
alias entries in taxonomies — appears in many surface forms:
`web-frontend`, `WebFrontend`, `web_frontend`, `web frontend`,
`APIGateway`. The skill normalizes all of these to a single kebab-case
form for **matching** purposes. The canonical, kebab-case identifier
as stored in the taxonomy or graph is what gets persisted.

## 6-step normalization algorithm

Applied in order to the raw input string:

1. Insert `-` before each uppercase letter that follows a lowercase
   letter or digit.
   (`webFrontend` → `web-Frontend`)

2. Insert `-` before the last uppercase letter of an uppercase run
   that is followed by a lowercase letter, to handle acronyms.
   (`APIGateway` → `API-Gateway`)

3. Lowercase the whole string.

4. Replace any run of `_`, `.`, or whitespace with a single `-`.

5. Collapse runs of `--` into a single `-`.

6. Strip leading and trailing `-`.

## Examples

| Input            | Normalized       |
|------------------|------------------|
| `web-frontend`   | `web-frontend`   |
| `WebFrontend`    | `web-frontend`   |
| `webFrontend`    | `web-frontend`   |
| `web_frontend`   | `web-frontend`   |
| `web frontend`   | `web-frontend`   |
| `APIGateway`     | `api-gateway`    |
| `API gateway`    | `api-gateway`    |
| `--leading`      | `leading`        |
| `trailing--`     | `trailing`       |
| `double--dash`   | `double-dash`    |

## Usage rules

- The normalized form is used **only for comparison**: matching a user
  input token against the canonical names and aliases in the graph or
  taxonomy.
- Persisted output (in artifact YAML and state file) always uses the
  canonical name as stored in the graph — not the user's surface form.
- Normalization is applied to `$ARGUMENTS` on invocation, to any
  free-text mention of a node name during an interview, and to alias
  entries when building the graph from ingested docs.
- If normalization produces a string that does not match
  `^[a-z][a-z0-9]*(-[a-z0-9]+)*$`, it is an invalid name. Report
  `name does not match pattern` and stop (same as Step 0 validation
  for explicit `$ARGUMENTS` tokens; for interview-time discovery,
  prompt the user to pick a valid name).
