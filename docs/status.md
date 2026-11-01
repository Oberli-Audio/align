# Status - <product> <version> (<date>)
Tier <S|P|F>, track <I|E|C|A>, at gate G<n>. Recipe D.8.<n>.

## Gates
| Gate | State | Evidence (command -> number, test name, log) |
|---|---|---|
| G0 | closed <date> | brief.md confirmed |
| G1 | closed <date> | see decisions |
| G3 | open | `python3 tools/measure/alias.py --note 96 --seed 1` -> -64.2 dB (target < -60) |
| G6 | - | `validate_plugin.py full` -> <exit>, hosts: Live 10.1 Rosetta <date>, Live Windows <date> |

## Listening debt
- <date>: <change measured, not heard; the renders to A/B>

## Open exceptions
- EX-<n> <date>: <rule or target>; measured <value> vs <threshold> by `<command>`; shipping is acceptable because <...>; **unacceptable if** <number>, as test `<name>` | re-checked when <...>. Friends: <one sentence a friend can notice, or none>

## Handoff
Task: <one line>. Plan: 1. [x] ... 2. [ ] ... (next) 3. [ ] ...
Working tree: <clean | files>. Build: <green | red>. Tests: <n pass / n fail - which>.
Open questions for the owner: <...>
Next command: `...`

## Decisions
- <date>: G1 family <...>; trade-off <...>; departures from S: <row> because <...>, rejected if <measurement>
- <date>: <negative result from the stop rule, resolved exception with its resolution, a constant and why>
