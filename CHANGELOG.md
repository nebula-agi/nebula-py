# Changelog

## [1.6.2](https://github.com/zeroset-inc/nebula-python/compare/v1.6.1...v1.6.2) (2026-06-10)


### Bug Fixes

* regenerate from nebula@8acf062 ([#123](https://github.com/zeroset-inc/nebula-python/issues/123)) ([d4c0208](https://github.com/zeroset-inc/nebula-python/commit/d4c0208f0352b138f9c84f6bd3f5cb998e49e0e5))

## [1.6.1](https://github.com/zeroset-inc/nebula-python/compare/v1.6.0-rc.0...v1.6.1) (2026-06-02)


### Bug Fixes

* regenerate from nebula@9463352 ([#31](https://github.com/zeroset-inc/nebula-python/issues/31)) ([1be7b16](https://github.com/zeroset-inc/nebula-python/commit/1be7b164e9ef2ce640666d75a8be2021164d09bd))
* regenerate from nebula@e5ade13 ([bcfbc2b](https://github.com/zeroset-inc/nebula-python/commit/bcfbc2b960151d4910bc7e75dbdd6ea48ddbb99b))

## [1.6.0-rc.0](https://github.com/zeroset-inc/nebula-python/compare/v1.5.0...v1.6.0-rc.0) (2026-05-25)


### Features

* regenerate from nebula@42d478d ([#25](https://github.com/zeroset-inc/nebula-python/issues/25)) ([5be65f9](https://github.com/zeroset-inc/nebula-python/commit/5be65f968ef38c35f086996267aa9e88657ca88d))
* regenerate from nebula@482822c ([#28](https://github.com/zeroset-inc/nebula-python/issues/28)) ([ed9d0bf](https://github.com/zeroset-inc/nebula-python/commit/ed9d0bfce72453887f6a15239ab914585f6ac579))
* regenerate from nebula@73d86ef ([#29](https://github.com/zeroset-inc/nebula-python/issues/29)) ([9170d0f](https://github.com/zeroset-inc/nebula-python/commit/9170d0f696b7faf8a1f5c7d9e8a08a194666aafe))


### Chores

* move prerelease config under packages."." ([6bfd53f](https://github.com/zeroset-inc/nebula-python/commit/6bfd53ffc0121a1b89bd8c0b3ab4da86f504fcdc))
* switch release-please to RC prerelease mode ([32fada2](https://github.com/zeroset-inc/nebula-python/commit/32fada219c0658fc2352309415b6114ce19c5dbf))

## [1.5.0](https://github.com/zeroset-inc/nebula-python/compare/v1.4.0...v1.5.0) (2026-05-25)


### Features

* regenerate from nebula@b90fb4a ([#20](https://github.com/zeroset-inc/nebula-python/issues/20)) ([c697dff](https://github.com/zeroset-inc/nebula-python/commit/c697dffc1672dbeeca1858ee405d8c5b18296514))

## [1.4.0](https://github.com/zeroset-inc/nebula-python/compare/v1.3.0...v1.4.0) (2026-05-24)


### Features

* regenerate from nebula@88ca786 ([#17](https://github.com/zeroset-inc/nebula-python/issues/17)) ([0160d8d](https://github.com/zeroset-inc/nebula-python/commit/0160d8d303393c4fddda9598037f154f81379dee))

## 1.3.0 (2026-04-27)

Full Changelog: [v1.2.2...v1.3.0](https://github.com/nebula-agi/nebula-python/compare/v1.2.2...v1.3.0)

### Features

* [codex] Clean up replayed playground memories ([0dfc69d](https://github.com/nebula-agi/nebula-python/commit/0dfc69df82f36929e528241e9a3ab2a2d593daa4))
* [codex] Fix EngramResponse OpenAPI example ([e30c479](https://github.com/nebula-agi/nebula-python/commit/e30c4791c3b84853e87c88ed7ce19809540ebc2c))
* [codex] Harden memory write validation contracts ([d55ce58](https://github.com/nebula-agi/nebula-python/commit/d55ce58c5b61eee2f468b5c054645e151fe8ec64))
* add nebula devex facade ([327f061](https://github.com/nebula-agi/nebula-python/commit/327f0610830c345b4899ecc4255ba6d6c4e78b55))
* api: honor chunks_limit on memory listing ([659d3c3](https://github.com/nebula-agi/nebula-python/commit/659d3c331dd4812b534172d1b8984b85a0723be9))
* engram: replace generated summaries with deterministic engram_context ([11e00ee](https://github.com/nebula-agi/nebula-python/commit/11e00ee6197de3b4c93f5c5d59a89f15b6a3d9ec))
* NQL overhaul v2 - clean cherry-pick baseline from [#526](https://github.com/nebula-agi/nebula-python/issues/526) ([c8d1366](https://github.com/nebula-agi/nebula-python/commit/c8d1366109d2726246a960707e5c9debb0ee2b2c))
* Remove legacy append chunk IDs from public contract ([ec543ad](https://github.com/nebula-agi/nebula-python/commit/ec543ad4d7f04996656a7ab8f6d362d47cf43b1e))
* Rename MemoryRecall response fields to adjective-uniform shape ([d3fda51](https://github.com/nebula-agi/nebula-python/commit/d3fda5130620ff961b5956a8ab8957e5a3375cd8))
* sdks/python: SnapshotEnvelope dataclass + typed export/import/search/add ([d4850d3](https://github.com/nebula-agi/nebula-python/commit/d4850d31ad4ae0c0a3234b3ea01db2d352ff74bd))
* Stabilize memory create SDK response schema ([54223f7](https://github.com/nebula-agi/nebula-python/commit/54223f7d3b3c24c23850e4b4bc4f9d0a625232ba))


### Bug Fixes

* harden dx facade compatibility ([#5](https://github.com/nebula-agi/nebula-python/issues/5)) ([219492f](https://github.com/nebula-agi/nebula-python/commit/219492ff070d2d39ccc0de609a11574669fdb6c4))
* **types:** allow pyright to infer TypedDict types within SequenceNotStr ([426e1c2](https://github.com/nebula-agi/nebula-python/commit/426e1c2d4c530a2524bc5b2d5790f8afd365e457))
* use async_to_httpx_files in patch method ([db8be2a](https://github.com/nebula-agi/nebula-python/commit/db8be2a29c33dc0d71d457ccecb5c3c96c6f9845))


### Chores

* add missing docstrings ([0393792](https://github.com/nebula-agi/nebula-python/commit/0393792d11323c21520ccd5693ef9c8e43c7a47e))
* **internal:** add `--fix` argument to lint script ([afa73fd](https://github.com/nebula-agi/nebula-python/commit/afa73fdf311affde54f5b0437adff64a77838c30))
* **internal:** add missing files argument to base client ([e79b5f7](https://github.com/nebula-agi/nebula-python/commit/e79b5f73aff54fb3ee2b5c54755ef054ce26e6f9))
* **internal:** more robust bootstrap script ([6da9e21](https://github.com/nebula-agi/nebula-python/commit/6da9e21c7c0c101c193d0b62e21ec68f6fc63c23))
* seed release baseline ([#4](https://github.com/nebula-agi/nebula-python/issues/4)) ([1561427](https://github.com/nebula-agi/nebula-python/commit/15614278e6459e97d6c0bc29b635fd4773a43ceb))
* speedup initial import ([01adfc0](https://github.com/nebula-agi/nebula-python/commit/01adfc08053fa2371c6264ed30b4978b38160b27))
* update SDK settings ([41a4a78](https://github.com/nebula-agi/nebula-python/commit/41a4a78c5944d902e5687fe9ace59d4ae818c37a))
* update SDK settings ([936b50a](https://github.com/nebula-agi/nebula-python/commit/936b50a4ba506394068cf52b2c5d470f43eadf23))
* update SDK settings ([cd61be2](https://github.com/nebula-agi/nebula-python/commit/cd61be2877083366a050c5a8b5413e21dea49519))
* update SDK settings ([b5d5785](https://github.com/nebula-agi/nebula-python/commit/b5d5785a1b33d55e78f5b68ab10d6377342f5d3d))
* update SDK settings ([54d2013](https://github.com/nebula-agi/nebula-python/commit/54d20131ca419a57c75f6779506e3937a1cca0e5))
* update SDK settings ([576c1f0](https://github.com/nebula-agi/nebula-python/commit/576c1f07cb7f7f8dd771092eb1ad85578cb060e6))
* update SDK settings ([631893f](https://github.com/nebula-agi/nebula-python/commit/631893f6398b13445e1e0ccaf21f5ea6c3aae50a))


### Refactors

* **internal:** switch from rye to uv ([cb98a73](https://github.com/nebula-agi/nebula-python/commit/cb98a7357bb6fdbb0e6609780f914fcc3bb8f692))
