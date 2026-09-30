# IMG.DAT 포맷 명세 (랑그릿사 I&II Dramatic Edition, Sega Saturn)

세션: "IMG 코덱 역공학" (2026-07-14). 서브에이전트 라이브 RE + 정적 디스어셈블 + 그라운드트루스 검증. **상태: ✅ 완전 해결·검증됨.**

## 1. 컨테이너 — ✅ 확정·검증됨

파일 선두에 big-endian u32 **오프셋 테이블**.

| 항목 | 값 |
|---|---|
| `u32[0]` | 테이블 바이트 크기 → 엔트리 수 = `u32[0] // 4` |
| `u32[i]` | 리소스 i의 파일 오프셋 |
| 리소스 i | `buf[off[i] : off[i+1])`, 마지막은 파일 끝까지 |
| LANG2 | 234 리소스, 파일 0x85572 (u32[0]=0x3a8) |
| LANG1 | 207 리소스, 파일 0x7da40 (u32[0]=0x33c) |

`parse_archive` / `build_archive`가 **양 아카이브 무손실 라운드트립**. 오프셋 테이블 재빌드·재삽입에 그대로 사용. 리소스 마지막(#233 LANG2)은 길이 0(더미).

## 2. 리소스 헤더

`c0 01` 등 선두 바이트는 **압축 비트스트림의 일부**(별도 매직 아님, skip=0). byte0=0xC0, byte1∈{0x01,0x29,0x30}은 그저 각 리소스 비트스트림의 첫 바이트가 그렇게 시작할 뿐이다(초기 "타입/사전 코드" 가설은 오답으로 폐기 — 프리로드 사전 없음).

## 3. 압축 — ✅ 커스텀 MSB-first 프리픽스 LZ (완전 규명·검증)

**★검증**: 각 리소스가 0x2000바이트 VDP2 VRAM char 뱅크로 압축해제되며 라이브 덤프(`vdp2vram.bin`)와 **바이트 일치**(res#1/5/6/27 = 100%, res#0 = 99.5%; 소수 불일치는 캡처 후 덮인 타일). 리소스↔뱅크: res0→VRAM 0x20000, res5→0x22000, res6→0x24000, res1→0x26000, res27→0x28000 …(씬 로드 순). **decompress(compress(x))==x 도 전 233(LANG2)/206(LANG1) 리소스 통과.** ★초기 "PRS" 가설은 오답 — PRS는 LSB-first, 실제 코덱은 **MSB-first**라 전부 실패했던 것.

### 디컴프레서 SH-2 코드 (LANG2.BIN, 로드베이스 0x06010000; 디스어셈블 1:1 대조)
| 함수 | 주소(L2) | 역할 |
|---|---|---|
| 메인 디코드 루프 | `0x0601158c` (L1: `0x0601159c`) | r4=출력버퍼, r5=압축원(리소스 선두). 토큰 트리 |
| `get_bit` | `0x0601138c` | **MSB-first** 1비트 (test 0x80 → shift left; bitcount==8이면 리필) |
| `get_byte` | `0x060113dc` | 비트경계 8비트 = get_bit×8 (헬퍼 `0x0606d35c`=>>, `0x0606d3e0`=<<) |
| `get_nibble` | `0x06011460` | 4비트 = get_bit×4 |
| short-copy | `0x06011534` | `copy(dist=nibble, 0→16;  len 1/2/3)` |
| byte-copy | `0x06011564` | `copy(dist=byte, 0→256;   len 2/3/4)` |
| copy 프리미티브 | `0x060114f4` | `out[out_ptr-dist]` 오버랩 복사(dist==0 → 256) |

- 엔진은 L1/L2 동일 구조(오프셋 ~+0x50). 압축원 = `0x20200000`(언캐시 미러)+table[i] = 리소스 선두(offset 0부터가 비트스트림).
- get_byte/get_nibble는 각각 get_bit 8·4회와 **동치**(둘 다 MSB-first 순차 추출) — 헬퍼 시프트 방향과 무관하게 `nbits(8)`/`nbits(4)`로 정확.

### 토큰 포맷 (MSB-first 프리픽스 코드)
```
loop:
  bit==1  → LITERAL:
      11        → 8비트 리터럴
      100       → 4비트값(0x00~0x0F) 리터럴
      10100→0x10  10101→0x30  10110→0x80  10111→0xFF   (빈출 바이트 단축)
  bit==0  → MATCH (선행 0 뒤 unary 1-run으로 길이/모드 선택):
      00        → copy(len=1, dist=nibble[0→16])
      010       → copy(len=2, dist=nibble[0→16])
      0110      → copy(len=3, dist=nibble[0→16])
      01110     → copy(len=2, dist=byte[0→256])
      011110    → copy(len=3, dist=byte[0→256])
      0111110   → copy(len=4, dist=byte[0→256])
      01111110  → LONG: len=nibble+5 (5~20), dist=byte[0→256]
      01111111  → END
```
구현: `img_codec.decompress()` / `img_codec.compress()`.

## 4. compress (인코더) — ✅ 무손실

MSB-first 비트라이터(위 토큰의 역인코딩). 그리디 최장매치(오버랩 매치 조건 = `raw[i+k]==raw[i+k-d]`). 리터럴 우선순위(비용 bit): 0x10/0x30/0x80/0xFF=5, 니블(≤0x0F)=7, 바이트=10. 매치: short 6/7/8, byte 13/14/15, long 20. **재압축 크기 ≈ 원본 105%**(offset 테이블 재빌드로 흡수; 전체 아카이브 재빌드→재파싱→재압축해제 시 타일 234/234·207/207 동일 확인).

## 5. 압축해제 파이프라인 특성 (라이브 RE 기록)
- 실제 디컴프는 **씬(배틀프렙/배틀) 진입 또는 콜드부트 시 1회**. 메뉴 네비게이션은 char_data를 타일맵 스왑으로 재사용(재트리거 안 됨).
- 압축원 read·출력 write 양단이 DMA/비동기 잡큐(cmd 3/4/5)로 처리돼 CPU read/write BP로는 디컴프 순간을 놓치기 쉬움. 코덱 자체는 정적 디스어셈블로 확정했으므로 라이브 검증은 불필요(그라운드트루스 vdp2vram 대조로 이미 완료).
- ⚠ emucap Mednafen `physical` 단일주소 exec BP는 하위 12비트만 매칭해 오탐(예: `0x0601158c` BP가 `0x0606b58c`에서 발동) — 향후 exec BP 쓸 땐 히트 후 PC 확인 필수. `physical` 주소공간(SCU DMA 0x25FE00xx) 미구현.

## 6. 다음 단계 (그래픽 한글화 본작업)
코덱은 완결. 남은 것은 **한글 렌더링 파이프라인**:
1. 메뉴 라벨(兵士配属/アイテム装備/指揮官配置/出撃, 攻撃/防御/移動/待機/魔法 등)이 **어느 리소스·타일**인지 특정 — 각 리소스 decompress→4bpp 타일 렌더(팔레트 `data/cram.bin`)로 시각 확인.
2. 해당 타일에 한글을 안티에일리어스 4bpp(음영 1~e)로 재렌더(원 아트 스타일 매칭).
3. `compress()`로 재압축 → `build_archive()`로 오프셋테이블 재빌드 → IMG.DAT 디스크 삽입(`disc_tool`) → 실기 검증.

## 7. 파일
- `img_codec.py` — parse_archive/build_archive/decompress/**compress** 전부 검증됨 + 셀프테스트.
- `sh2dis.py` — 미니 SH-2 디스어셈블러(디컴프레서 RE에 사용).
- 진단(역사): `prs.py`/`brute_prs.py`/`brute.py`/`try_lzss.py`(PRS·LZSS 반증 기록), `decode_v2.py`.
