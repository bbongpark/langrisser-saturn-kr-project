#!/usr/bin/env python3
"""
langr_compress.py — Langrisser Saturn 스테이지 블롭 압축 코덱(커스텀 LZ류).

`decode()`는 탭9 조사 세션이 DerEditor의 `Compression` 클래스(decompiled/
DerEditor/Compression.cs)를 파이썬으로 이식한 것을 그대로 가져왔다(실측
검증됨 — 92스테이지 전부 정상 디코딩 확인, `_tab9_probe.py` 참고).

`encode()`는 **이번 세션에 새로 작성**했다 — 원본 압축기(Compression.Encode)는
디컴파일 안 했고, decode()가 받아들이는 포맷 규칙만 보고 **독자적으로 맞춰
쓴 인코더**다. 그래서 원본과 바이트 단위로 같은 압축 결과가 나오진 않지만
(압축은 유일하지 않다), **decode(encode(x)) == x 는 92개 실제 스테이지 블롭
전부로 검증했다** — 이게 유일하게 필요한 정합성 기준이다(디코더는 우리가
안 건드렸고 게임이 실제로 쓰는 것과 같으니까).

비트 포맷 (MSB 우선, 바이트 순서대로 이어붙인 비트스트림):
  11 + 8bit                     리터럴 1바이트
  00 + 4bit(d, 0=16)             1바이트 역참조, 거리 1~16
  01 + 0   + 4bit(d,0=16)        2바이트 역참조, 거리 1~16
  01 + 10  + 4bit(d,0=16)        3바이트 역참조, 거리 1~16
  01 + 110 + 8bit(d,0=256)       2바이트 역참조, 거리 1~256
  01 + 1110+ 8bit(d,0=256)       3바이트 역참조, 거리 1~256
  01 + 11110+8bit(d,0=256)       4바이트 역참조, 거리 1~256
  01 + 111110+4bit(len-5)+8bit(d,0=256)   5~20바이트 역참조, 거리 1~256
  01 + 111111                    스트림 종료 마커(이 인코더는 항상 마지막에 씀)
  10 + 3bit                      상수 바이트(16/48/128/255 중 하나, 코드 4종만
                                  정의돼 있어 **이 인코더는 안 쓴다** — 나머지
                                  3bit 패턴의 디코더 동작이 불확실해서 회피)

역참조는 `out[j] = out[j-dist]`를 **한 바이트씩** 반복하는 구조라(디코더 원본
그대로) `dist < length`인 자기참조(겹침, 예: 같은 바이트 반복하는 RLE)도
정상 동작한다 — 인코더의 매치 탐색도 이걸 그대로 활용한다.
"""

# ---------- decode (검증된 기존 구현 이식, 손대지 않음) ----------

def decode(data: bytes) -> bytes:
    text = "".join(f"{b:08b}" for b in data)
    n = len(text)
    out = bytearray(len(data) * 12 + 16)
    i = 0
    j = 0

    def take(k):
        nonlocal i
        s = text[i:i + k]
        i += k
        return s

    while i < n - 1:
        tag = take(2)
        if tag == "11":
            v = int(take(8), 2)
            out[j] = v
            j += 1
            continue
        if tag == "10":
            v3 = take(3)
            m = {"100": 16, "101": 48, "110": 128, "111": 255}
            out[j] = m.get(v3, 0)
            j += 1
            continue
        if tag == "00":
            v4 = int(take(4), 2)
            dist = v4 if v4 != 0 else 16
            out[j] = out[j - dist]
            j += 1
            continue
        if tag == "01":
            unary = ""
            while True:
                c = text[i]
                if c != "0":
                    unary += c
                    i += 1
                    if unary == "111111":
                        i -= 1
                        break
                    continue
                else:
                    unary += c
                    i += 1
                    break
            if unary == "0":
                dist = int(take(4), 2)
                dist = dist if dist != 0 else 16
                for _ in range(2):
                    out[j] = out[j - dist]
                    j += 1
            elif unary == "10":
                dist = int(take(4), 2)
                dist = dist if dist != 0 else 16
                for _ in range(3):
                    out[j] = out[j - dist]
                    j += 1
            elif unary == "110":
                dist = int(take(8), 2)
                dist = dist if dist != 0 else 256
                for _ in range(2):
                    out[j] = out[j - dist]
                    j += 1
            elif unary == "1110":
                dist = int(take(8), 2)
                dist = dist if dist != 0 else 256
                for _ in range(3):
                    out[j] = out[j - dist]
                    j += 1
            elif unary == "11110":
                dist = int(take(8), 2)
                dist = dist if dist != 0 else 256
                for _ in range(4):
                    out[j] = out[j - dist]
                    j += 1
            elif unary == "111110":
                lenex = int(take(4), 2)
                dist = int(take(8), 2)
                dist = dist if dist != 0 else 256
                for _ in range(lenex + 5):
                    out[j] = out[j - dist]
                    j += 1
            elif "111111" in unary:
                break
            continue
        break
    return bytes(out[:j])


# ---------- encode (신규 작성) ----------

MAX_LEN = 20
MAX_DIST_SHORT = 16
MAX_DIST_LONG = 256


def _best_match(data: bytes, j: int) -> tuple:
    """data[:j]를 사전으로 삼아 data[j:]에서 가장 긴 매치를 찾는다.
    반환: (length, distance) — 매치 없으면 (0, 0)."""
    n = len(data)
    max_len = min(MAX_LEN, n - j)
    if max_len < 1:
        return (0, 0)
    best_len, best_dist = 0, 0
    max_dist = min(MAX_DIST_LONG, j)
    for dist in range(1, max_dist + 1):
        length = 0
        while length < max_len and data[j - dist + length] == data[j + length]:
            length += 1
        # 거리<=16인 1바이트 매치도 유효하지만, 그보다 긴 매치가 이미 있으면 그게 낫다
        if length > best_len or (length == best_len and dist < best_dist):
            best_len, best_dist = length, dist
    return (best_len, best_dist)


def _emit_len2plus(bits: list, length: int, dist: int):
    """길이 2~20, 거리 1~256인 매치를 비트로 인코딩(01 태그 이후 부분)."""
    d16 = dist if dist != 16 else 0   # 4bit 필드: 16은 0으로 인코딩
    d256 = dist if dist != 256 else 0  # 8bit 필드: 256은 0으로 인코딩
    if length == 2 and dist <= MAX_DIST_SHORT:
        bits.append("0"); bits.append(f"{d16:04b}")
    elif length == 3 and dist <= MAX_DIST_SHORT:
        bits.append("10"); bits.append(f"{d16:04b}")
    elif length == 2:
        bits.append("110"); bits.append(f"{d256:08b}")
    elif length == 3:
        bits.append("1110"); bits.append(f"{d256:08b}")
    elif length == 4:
        bits.append("11110"); bits.append(f"{d256:08b}")
    elif 5 <= length <= 20:
        bits.append("111110"); bits.append(f"{length-5:04b}"); bits.append(f"{d256:08b}")
    else:
        raise ValueError(f"unsupported length {length}")


def encode(data: bytes) -> bytes:
    bits = []
    j = 0
    n = len(data)
    while j < n:
        length, dist = _best_match(data, j)
        if length >= 2 and dist <= MAX_DIST_LONG:
            bits.append("01")
            _emit_len2plus(bits, length, dist)
            j += length
        elif length == 1 and dist <= MAX_DIST_SHORT:
            d16 = dist if dist != 16 else 0
            bits.append("00"); bits.append(f"{d16:04b}")
            j += 1
        else:
            bits.append("11"); bits.append(f"{data[j]:08b}")
            j += 1
    # 스트림 종료 마커: 01 + 111111
    bits.append("01"); bits.append("111111")

    bitstring = "".join(bits)
    pad = (-len(bitstring)) % 8
    bitstring += "0" * pad
    out = bytearray(len(bitstring) // 8)
    for k in range(0, len(bitstring), 8):
        out[k // 8] = int(bitstring[k:k + 8], 2)
    return bytes(out)


if __name__ == "__main__":
    import random
    random.seed(0)
    # 무작위 데이터 + 반복 패턴 섞어서 round-trip 검증
    tests = []
    tests.append(bytes(random.randint(0, 255) for _ in range(200)))
    tests.append(bytes([5, 5, 5, 5, 5, 5, 5, 5] * 10))
    tests.append(bytes(range(50)) * 4)
    tests.append(b"")
    tests.append(bytes([0]))
    for i, t in enumerate(tests):
        comp = encode(t)
        back = decode(comp)
        assert back == t, f"test {i} round-trip 실패: len(t)={len(t)} len(back)={len(back)}"
        ratio = f"{len(comp)}/{len(t)}" if t else "0/0"
        print(f"test {i}: OK  compressed {ratio} bytes")
    print("langr_compress self-test OK")
