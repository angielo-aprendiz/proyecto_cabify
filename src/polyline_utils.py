"""Decodificador de polylines codificadas (Google/Cabify)."""


def decode_polyline(encoded: str) -> list[list[float]]:
    if not encoded:
        return []

    coords = []
    index, lat, lng = 0, 0, 0

    while index < len(encoded):
        for is_lng in (False, True):
            shift, result = 0, 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if (result & 1) else (result >> 1)
            if is_lng:
                lng += delta
            else:
                lat += delta
        coords.append([lat / 1e5, lng / 1e5])

    return coords
