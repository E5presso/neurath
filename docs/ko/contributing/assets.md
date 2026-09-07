# 독립 실행 자산
<!-- date: 2026-09-07; synced_from: source and documentation at 2456ae73ffaf818c04ea4419574218df36852805; English and Korean editions updated together -->

[사용 안내](../usage/index.md) · [기여자 안내](index.md)


[English](../../en/contributing/assets.md) · **한국어**

Neurath는 자체 런타임, 호스트 어댑터, 계약, 설치기를 관리합니다.
다른 저장소를 빌드 입력이나 실행 의존성으로 사용하지 않습니다.

`src/neurath/manifest.json`은 설치 패키지의 실행 코드와 자산 전체를 검증합니다.
비공개 개발 자료, 검증 원문, 설치 이력은 공개 배포본에 포함하지 않습니다.

독립 실행 자산을 살펴보려면 `neurath corpus /path/to/new-directory`를 사용하세요.
이 명령은 현재 배포본의 자산을 복사하며 다른 저장소를 읽지 않습니다.
