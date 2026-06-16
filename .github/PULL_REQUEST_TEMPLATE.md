## Summary

<!-- 이번 PR의 목적과 핵심 변경 사항을 간단히 적어주세요. -->

## Changes

- 

## Type of Change

- [ ] Feature
- [ ] Fix
- [ ] Refactor
- [ ] Docs
- [ ] Test
- [ ] Chore

## Interface / Contract Check

<!-- 변경된 항목만 체크. 없으면 비워두면 됩니다. -->

- [ ] Event Schema (`docs/interfaces.md` Section 2)
- [ ] API Contract (`docs/api_contract.md`)
- [ ] CurrentStatus (`docs/interfaces.md` Section 7-A)
- [ ] DB Schema (`src/api/database.py`)
- [ ] CLI 옵션 (`src/main.py`)
- [ ] Frontend Type (`frontend/src/types/event.ts`)
- [ ] Output Format (`outputs/events.jsonl`, `summary.json`, `result.mp4`)
- [ ] Environment / Dependency (`requirements.txt`, `frontend/package.json`)

> 체크된 항목이 있으면 관련 문서를 함께 업데이트하거나 Handoff에 명시하세요.

## Breaking Changes

- [ ] 없음
- [ ] 있음 (있으면 아래 펼쳐서 작성)

<details>
<summary>Breaking Change 상세 (있을 때만 작성)</summary>

영향 범위:

대응 방법:

ADR 필요 여부:

</details>

## Handoff / README

<!-- 다음 담당자에게 전달할 내용. README 갱신 필요하면 여기에 적어주세요. -->


<details>
<summary>Verification & Checklist (펼쳐서 확인)</summary>

**Verification**
- [ ] `pytest -q`
- [ ] React build
- [ ] 직접 실행 확인
- [ ] API 동작 확인

**Checklist**
- [ ] `outputs/`, `*.pt`, `node_modules/`, `.env` 포함 없음
- [ ] 민감정보/API 키/RTSP 비밀번호 포함 없음

</details>
