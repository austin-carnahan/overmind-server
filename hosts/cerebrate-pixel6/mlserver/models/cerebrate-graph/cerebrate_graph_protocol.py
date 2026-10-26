"""Wire protocol for cerebrate-graph (see cerebrate-graph/cerebrate-graph.cc
for the authoritative description).

Pure numpy, no MLServer imports, so the same module serves both the MLServer
adapter (cerebrate_graph_runtime.py, which sits next to it) and the direct
test client (cerebrate-graph/graph-client).

request  := u32 num_inputs, then tensors (num_inputs == 0 is DESCRIBE)
tensor   := u16 name_len, name, u8 dtype, u8 rank, rank x i64 dims,
            u32 data_len, data
response := typed frames [u8 type][u32 len][payload]: one DATA, then DONE;
            or a single ERROR.
"""
import json
import socket
import struct

import numpy as np

FRAME_DATA = 0
FRAME_DONE = 1
FRAME_ERROR = 2

# Generous: SAM encoder embeddings are ~16 MB across three outputs.
MAX_FRAME_BYTES = 256 * 1024 * 1024

# ONNXTensorElementDataType values <-> numpy dtypes. Little-endian only,
# which is every machine this project runs on.
ONNX_TO_NUMPY = {
    1: np.dtype("<f4"),
    2: np.dtype("u1"),
    3: np.dtype("i1"),
    4: np.dtype("<u2"),
    5: np.dtype("<i2"),
    6: np.dtype("<i4"),
    7: np.dtype("<i8"),
    9: np.dtype("?"),
    10: np.dtype("<f2"),
    11: np.dtype("<f8"),
    12: np.dtype("<u4"),
    13: np.dtype("<u8"),
}
# Keyed by kind + itemsize ("f4", "b1", ...) so byte order doesn't matter;
# encode_request converts to the little-endian dtype above.
NUMPY_TO_ONNX = {f"{d.kind}{d.itemsize}": code for code, d in ONNX_TO_NUMPY.items()}


class WorkerError(RuntimeError):
    """The worker answered with an ERROR frame (bad input name, shape, ...)."""


def encode_request(inputs: dict) -> bytes:
    """inputs: {name: numpy array}. An empty dict encodes a DESCRIBE request."""
    parts = [struct.pack(">I", len(inputs))]
    for name, array in inputs.items():
        array = np.ascontiguousarray(array)
        code = NUMPY_TO_ONNX.get(f"{array.dtype.kind}{array.dtype.itemsize}")
        if code is None:
            raise TypeError(f"input {name}: unsupported dtype {array.dtype}")
        name_bytes = name.encode("utf-8")
        data = array.astype(ONNX_TO_NUMPY[code], copy=False).tobytes()
        parts.append(struct.pack(">H", len(name_bytes)))
        parts.append(name_bytes)
        parts.append(struct.pack(">BB", code, array.ndim))
        parts.append(struct.pack(f">{array.ndim}q", *array.shape))
        parts.append(struct.pack(">I", len(data)))
        parts.append(data)
    return b"".join(parts)


def decode_tensors(payload: bytes) -> dict:
    """A DATA frame's payload -> {name: numpy array}, in the model's output order."""
    view = memoryview(payload)
    (count,) = struct.unpack_from(">I", view, 0)
    offset = 4
    outputs = {}
    for _ in range(count):
        (name_len,) = struct.unpack_from(">H", view, offset)
        offset += 2
        name = bytes(view[offset:offset + name_len]).decode("utf-8")
        offset += name_len
        code, rank = struct.unpack_from(">BB", view, offset)
        offset += 2
        dims = struct.unpack_from(f">{rank}q", view, offset)
        offset += 8 * rank
        (data_len,) = struct.unpack_from(">I", view, offset)
        offset += 4
        dtype = ONNX_TO_NUMPY.get(code)
        if dtype is None:
            raise ValueError(f"output {name}: unknown dtype code {code}")
        array = np.frombuffer(view[offset:offset + data_len], dtype=dtype).reshape(dims)
        offset += data_len
        outputs[name] = array
    if offset != len(payload):
        raise ValueError(f"DATA frame has {len(payload) - offset} trailing bytes")
    return outputs


def parse_done(payload: bytes) -> dict:
    fields = {}
    for token in payload.decode("utf-8", "replace").split():
        key, _, value = token.partition("=")
        fields[key] = int(value)
    return fields


def parse_frame_header(header: bytes) -> tuple:
    frame_type, length = struct.unpack(">BI", header)
    if length > MAX_FRAME_BYTES:
        raise ValueError(f"frame of {length} bytes exceeds {MAX_FRAME_BYTES}")
    return frame_type, length


def finish(frames: list, describe: bool):
    """frames: [(type, payload), ...] for one response, ending at DONE or
    ERROR. Returns (outputs_or_description, done_fields)."""
    data = None
    for frame_type, payload in frames:
        if frame_type == FRAME_ERROR:
            raise WorkerError(payload.decode("utf-8", "replace"))
        if frame_type == FRAME_DATA:
            data = payload
        elif frame_type == FRAME_DONE:
            if data is None:
                raise ValueError("DONE without a DATA frame")
            result = json.loads(data) if describe else decode_tensors(data)
            return result, parse_done(payload)
        else:
            raise ValueError(f"unknown frame type {frame_type}")
    raise ValueError("response ended without DONE or ERROR")


def _recv_exact(sock, length: int) -> bytes:
    chunks = []
    remaining = length
    while remaining:
        chunk = sock.recv(min(remaining, 1 << 20))
        if not chunk:
            raise ConnectionError("cerebrate-graph closed the connection")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def call(sock, inputs: dict):
    """Blocking request/response over an open socket. inputs={} is DESCRIBE.
    (asyncio streams already set TCP_NODELAY; plain sockets don't.)"""
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.sendall(encode_request(inputs))
    frames = []
    while True:
        frame_type, length = parse_frame_header(_recv_exact(sock, 5))
        frames.append((frame_type, _recv_exact(sock, length)))
        if frame_type in (FRAME_DONE, FRAME_ERROR):
            return finish(frames, describe=not inputs)


async def call_async(reader, writer, inputs: dict, timeout: float):
    """asyncio version of call(), for the MLServer adapter."""
    import asyncio

    writer.write(encode_request(inputs))
    await writer.drain()
    frames = []
    while True:
        header = await asyncio.wait_for(reader.readexactly(5), timeout=timeout)
        frame_type, length = parse_frame_header(header)
        payload = await asyncio.wait_for(reader.readexactly(length), timeout=timeout)
        frames.append((frame_type, payload))
        if frame_type in (FRAME_DONE, FRAME_ERROR):
            return finish(frames, describe=not inputs)
