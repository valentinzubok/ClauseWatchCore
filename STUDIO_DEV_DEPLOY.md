# ClauseWatch — Studio Dev (chain 61997) deploy record

| | |
|---|---|
| **Network** | GenLayer Studio Dev / Studio Next — chain `61997`, GenVM `v0.3.0-rc7` |
| **RPC** | `https://studio-dev.genlayer.com/api` |
| **Contract** | [`0x0B32c2f2aFbbf79963D9132f93912694e913bA6d`](https://explorer-studio-dev.genlayer.com/address/0x0B32c2f2aFbbf79963D9132f93912694e913bA6d) |
| **Owner** | `0x6f6077eC587f2964d30aCE8D803Edc27988046e3` |
| **Source** | [`contracts/ClauseWatch.py`](contracts/ClauseWatch.py) — byte-identical in both repos — runner `py-genlayer:5jycge4q8k23462jtb0b9fyey1s9qz928sz2nbrd9mg4sxqg2qng` |
| **Source sha256** | `37b3c7f7a18e66a9498baa74f1379bb165bd3269375573064a190f5858f02320` |
| **Console (separate repo)** | https://valentinzubok.github.io/ClauseWatch/ |
| **Watched page** | https://valentinzubok.github.io/ClauseWatch/fixtures/terms.html (in the [ClauseWatch repo](https://github.com/valentinzubok/ClauseWatch/blob/main/web/public/fixtures/terms.html)) |

## Verify that the deployed code equals the repository

```bash
curl -s -X POST https://studio-dev.genlayer.com/api -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"gen_getContractCode","params":["0x0B32c2f2aFbbf79963D9132f93912694e913bA6d"]}' \
  | python3 -c "import sys,json,base64,hashlib; print(hashlib.sha256(base64.b64decode(json.load(sys.stdin)['result'])).hexdigest())"
shasum -a 256 contracts/ClauseWatch.py
# both print 37b3c7f7a18e66a9498baa74f1379bb165bd3269375573064a190f5858f02320
```

## The demo is a real edit history

The watched page is a file in this repository, so every version the contract reacted to is a commit you can read:

| Commit | Edit | What ClauseWatch should say |
|---|---|---|
| initial | Terms v1: Pro 20 USD/seat/month, cancel any time, no ad sharing | baseline v1 frozen |
| `Demo fixture: cosmetic edit` | adds "Last reviewed 2026-09-20" | changed, **not material** |
| `Demo fixture: material edit` | 20 → 30 USD, prepaid annually, 30-day notice, analytics sharing | **material change** |

## On-chain lifecycle (all `ACCEPTED`, execution `SUCCESS`)

| # | Step | Result | Tx |
|---|------|--------|----|
| 0 | deploy (`owner_address` = `0x6f60…46e3`) | contract created | `0x8432a24f89fa046836529b3a8c10e50c0088844e58eb7bf670f024e5f01280eb` |
| 1 | `register_watch("demo/terms", …)` | baseline v1 frozen, sha256 `4451b053…` | `0x5aa6b2bdacf7fbd672e2ca0818471d87588f762a5e22e620f56ec6129a5e81a3` |
| 2 | `check` | **unchanged** — no alert, no LLM spend | `0xbd3c69f4c3d1baacd8ca806f4215684660df9701a36c1c9a2dfb1196e8b55e7b` |
| 3 | `check` after the cosmetic edit | hash differs → validators' LLMs agree **material: false**, `alert-1` | `0x1dcf6803746124be6b6f40cab616e43aaf9d356b6c684c5811cc5ba0dbc9bf66` |
| 4 | `check` after the material edit | hash differs → validators' LLMs agree **material: true**, `alert-2` | `0xd719916584c0eed6974cf0c541b7ba1fe4120d93de0614936550cd9bc3ec6e03` |

State after step 4: `checks 4`, `changes 2`, `material_changes 1`, baseline still v1 with the new version pending
acknowledgement. `alert-1` (cosmetic) and `alert-2` (material) sit side by side in `list_alerts`, each carrying both
hashes and the baseline version it was judged against.

## Demo video

[Demo video](https://github.com/valentinzubok/ClauseWatch/blob/main/assets/demo/clausewatch-demo.mp4): 2:43 recording of the live console, no mocks. It shows the watched page
and its commits, chain state loaded without a wallet, then `check` → **material change**, `acknowledge` → baseline v2,
and a second watch registered from scratch, ending on the transaction in the explorer.

For an unattended recording a small EIP-1193 wallet signing with test keys is injected in place of the MetaMask
popup; consensus waits are sped up 8x and rate-limit pauses are cut.

## Notes

- GitHub Pages serves the fixture with a ~10 minute CDN cache, so a check right after a commit can still see
  the previous version. That is honest behaviour for a monitor: it reports what validators actually fetched.
- Every write carries a Studio Dev fee deposit; the console has a faucet button for test GEN.
