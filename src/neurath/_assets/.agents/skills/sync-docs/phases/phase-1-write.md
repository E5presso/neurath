# Phase 1: 문서 작성

검증된 source로 documentation change를 draft합니다.

## 절차

1. code, test, manifest, approved plan, ADR을 source of truth로 사용합니다.
2. phase 0에서 선택한 docs만 수정합니다.
3. implementation log보다 간결하고 재사용 가능한 documentation을 선호합니다.
4. Neurath purpose가 unsettled이면 product-purpose-neutral language를 유지합니다.
5. 문서에 `date`와 `synced_from` 또는 equivalent source SHA metadata를 남깁니다.
6. Writer는 Verifier 역할을 수행하지 않습니다.

## Rule

Docs는 transient chat history가 아니라 durable behavior와 decision을 설명합니다.

## 완료 evidence

- `writer_report`
- `changed_docs`
- `source_sha`
- `frontmatter_or_metadata_check`
