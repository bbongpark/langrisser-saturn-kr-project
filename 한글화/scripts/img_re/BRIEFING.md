# IMG.DAT 압축 역공학 — 서브에이전트 브리핑

## 목표
세가 새턴 랑그릿사 I&II 한글패치. **배틀 메뉴/커맨드 라벨**(兵士配属/アイテム装備/指揮官配置/
出撃, 전투 커맨드 攻撃/防御/移動/待機/魔法/マニュアル 등)이 텍스트가 아니라 **IMG.DAT 안에
커스텀 압축된 4bpp 비트맵 그래픽**임을 확증했다. 이 압축을 역공학해 **① 압축해제 ② 무손실 재압축**
Python 구현을 만드는 것이 이 작업의 전부다. (한글 재렌더·재삽입은 그 다음 단계로, 이 브리핑 범위 밖.)

## 확정 사실 (에뮬레이터 라이브 RE로 검증됨)
- **IMG.DAT 구조**: 파일 선두가 big-endian u32 **오프셋 테이블**. `u32[0]`=0x3a8(L2)/0x33c(L1) = 테이블
  바이트 크기 → 엔트리 수 = u32[0]/4. 각 엔트리[i] = 리소스 i의 파일 오프셋. 리소스 i = [off[i], off[i+1]).
  마지막 리소스 끝 = 파일 크기. L2: 234개 리소스, 파일 0x85572. L1: 파일 0x7da40.
- **모든 리소스가 바이트 `c0 01`로 시작**. 그 뒤 `c0 XX` 또는 `07 XX` 패턴.
- **런타임**: 게임이 IMG.DAT **전체를 Low Work RAM(workraml) 오프셋 0x0에 그대로 로드**(offset 테이블이
  workraml 0x0에 있음 = `workraml.bin` 선두와 파일 선두 동일). 씬 로드 때 리소스를 VDP2 VRAM으로 압축해제
  (DMA 경유로 추정 — CPU read BP 미발동).
- **압축해제 결과 = 4bpp 8x8 타일**. VDP2 VRAM char_data에 상주. 메뉴 그래픽은 char_data 0x0부터:
  타일0=전부 0x00(빈 타일), 타일1~=창 프레임(`eeeee444 eeeee443 eeee4432…` 그라데이션), 이후 한자 글리프.

## 제공 데이터 (모두 `scripts/img_re/data/`)
- `LANG2_IMG.DAT`, `LANG1_IMG.DAT` — 원본 압축 아카이브 (= `kr-patch/original/`과 동일).
- `workraml.bin` (1MB) — 런타임 Low Work RAM 덤프. 오프셋 0x0에 LANG2_IMG.DAT 압축본 그대로.
- `vdp2vram.bin` (512KB) — 런타임 VDP2 VRAM 덤프. char_data 0x0부터 **압축해제된 메뉴 그래픽 타일**(정답 레퍼런스).
  - 0x000: 빈 타일(0x00×32)
  - 0x020: `eeeee444eeeee443eeee4432eeee4321…` (창 프레임)
  - 0x440~: 兵士配属 등 한자 글리프 타일 (charno 34~, 4bpp 그라데이션 픽셀)
- `state.json`, `regions.json`, `cram.bin`(팔레트) — 참고.

## 작업 순서 (권장)
1. **오프셋 테이블 파싱** → 234개 리소스 경계. 작은 리소스(#4=250B, #7=222B)부터 구조 분석.
2. **압축 포맷 역공학**: 압축본(리소스) ↔ 압축해제본(vdp2vram char_data) 정렬로 토큰 의미 규명.
   - 어느 리소스가 char_data 0x0 그래픽을 내는지 찾으려면: 압축해제 결과가 `00×32 + eeeee444…`로 시작하는
     리소스를 찾는다. `c001` 다음 바이트열과 이 레퍼런스를 대조.
   - LZSS/LZ77 계열 가능성 높음(플래그 비트 + 리터럴/백레퍼런스 복사). RLE 요소(연속 0x00·0x77 런)도 확인.
     제어워드 `c0 01`, `c0 XX`, `07 XX` 패턴의 비트 의미를 가설→검증 반복.
3. **decompress(resource_bytes) -> bytes** 구현. 검증: 메뉴 리소스 압축해제 결과가 vdp2vram char_data와
   **바이트 일치**. 나아가 **전 234개 리소스가 에러 없이 압축해제**되고 크기가 4bpp 타일 배수(32의 배수)로
   떨어지는지 확인.
4. **compress(raw_bytes) -> resource_bytes** 구현(무손실). 검증: **전 리소스 round-trip**
   `decompress(compress(decompress(r))) == decompress(r)` (재압축이 원본과 바이트 동일일 필요는 없음 —
   압축해제 결과만 일치하면 됨. 단 게임이 받아들이는 유효 스트림이어야 함).
5. 결과물: `scripts/img_re/img_codec.py` (parse_archive / decompress / compress / build_archive) +
   셀프테스트 + 짧은 `FORMAT.md`(포맷 명세). 메뉴 라벨이 **어느 리소스 인덱스**인지도 보고.

## 세션8 추가 규명 (2026-07-14, 압축 해제 메커니즘 좁힘)
- **SCU DSP 압축해제 아님**: `dspprog` 전부 `f0000000`(NOP) = DSP 미사용.
- **압축 해제 입출력 양단이 DMA로 가려짐**: (a) 압축원 workraml 0x3a8~0x40000에 **CPU read BP 미발동**(배틀 로드/전환 중), (b) 압축해제 출력 VDP2 VRAM char_data 0x20~0x60에 **CPU write BP 미발동**(튜토리얼 그래픽 렌더 중에도 안 걸림 = VRAM 업로드가 DMA), (c) **압축해제된 프레임(`eeeee444…`)이 workramh/workraml 어디에도 없음**(오직 vdp2vram에만) = 디컴프레서 출력이 워크버퍼 상주 없이 DMA로 VRAM 직행(또는 즉시 재사용).
- **∴ 정공 catch 경로**: CPU read/write BP로는 못 잡음. 남은 방법 — ① **시나리오/배틀 init 시점 트레이스**(캐시 전 최초 압축해제; 콜드부트→에피소드메뉴/캐릭터메이킹 직후에서 BP 대신 `set_trace`로 실행 로그 후 IMG.DAT 주소 접근 프레임 격리), ② **DMA 셋업 추적**(CPU가 DMA 레지스터에 압축원/워크버퍼 주소 기입하는 지점 = 디컴프레서 전후 경계; Mednafen엔 dma BP 없어 레지스터 write watch 필요), ③ **디컴프레서 코드 정적 탐색**(워크램 IMG.DAT 주소 상수 참조 코드). ⚠캐릭터메이킹 상태(ep2_charmake_result.state)→예→전투튜토리얼은 길고, 시나리오1 init 도달 전까지 여러 화면.
- **환경 제약**: 이 emucap Mednafen 빌드는 **게임 세이브가 백업RAM에 안 써짐**(별개 이슈, 그래픽과 무관하나 로드창 검증엔 영향). reset이 콜드부트 안 함(같은 상태 유지) — 콜드부트는 `launch(replace=true)` 필요.
- **★DMA 압축 해제 이중 확인(2회 독립 테스트)**: (1) ep2_charmake_result.state→튜토리얼→시나리오1 프렙 메뉴(兵士配属 최초 렌더)까지 진행, read BP(workraml 0x400~0x86000) **미발동**. Ep2는 char making 전에 전투가 없어 그 시점 VRAM이 클린=유효한 최초 압축 해제. (2) 콜드부트→Ep2→새 게임→오프닝→퀴즈까지 재확인. **결론: CPU가 workraml의 IMG.DAT를 직접 안 읽음 → DMA로 워크버퍼에 복사 후 CPU가 거기서 압축 해제, 출력도 DMA로 VRAM. workramh에 압축 리소스 복사본 없음(`c001` 0건), 압축해제 프레임도 workram에 없음(VRAM 전용).** CPU read/write BP로는 못 잡음이 확정.
- **★남은 유일 catch 경로 = DMA 셋업 추적**: 게임이 압축해제 결과를 VRAM으로 DMA할 때 CPU가 DMA 레지스터(SCU DMA 0x25FE00xx 또는 SH-2 온칩 DMAC 0xFFFFFExx)에 **소스 주소(=디컴프레서 출력 워크버퍼)**를 기입. 그 write를 잡으면 워크버퍼 위치 확보→그 버퍼에 write BP 재장전→디컴프레서 코드 PC 포착→SH-2 트레이스로 코덱 규명. Mednafen엔 dma BP 없으니 physical/레지스터 영역 write watch 필요(memory_type 지원 여부 확인 요). 대안: 시나리오1 프렙 직전에 `set_trace`로 실행로그 캡처 후 IMG.DAT 접근/타일생성 루프 격리(트레이스 대용량 주의).
- **★코덱 크랙 후 남는 파이프라인(별도 큰 작업)**: decompress/compress Python 구현 → 안티에일리어싱 4bpp 타일에 한글 렌더(아트 스타일 매칭) → 무손실 재압축 → IMG.DAT 오프셋테이블 재계산 재삽입 → 인게임 검증. **∴ 그래픽 버튼 한글화는 전용 다세션 서브프로젝트.** 참고: 兵士配属/アイテム装備/指揮官配置는 SCEN 텍스트에 없음(그래픽 확정). 전투커맨드 攻撃/防御/移動/待機/魔法·セーブ/ロード는 SCEN 여러 리프에 텍스트로 존재하나 (2,0) 등에서의 그 출현은 메뉴 버튼 소스가 아니라 대사/메시지 용례(브리핑 라이브 RE로 메뉴는 그래픽 확증).

## 주의
- big-endian(SH-2/Saturn). 타일은 4bpp = 픽셀당 4비트, 8x8=32바이트/타일.
- 재압축은 **게임 디컴프레서가 해석 가능한 유효 스트림**이어야 한다(포맷 규칙 준수). 크기가 커져도 되지만
  (원본보다 길어도) IMG.DAT 오프셋 테이블 재계산으로 흡수 가능 — 단 그건 다음 단계.
- 실패해도 부분 진전(포맷 일부 규명, 압축해제만 성공 등)을 명확히 보고. 추측은 반드시 레퍼런스로 검증.
