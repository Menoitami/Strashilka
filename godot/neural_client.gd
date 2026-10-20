class_name NeuralClient
extends RefCounted

signal result_received(header: Dictionary, blobs: Dictionary)
signal connection_changed(connected: bool)

const MAX_HEADER := 65536
const MAX_BODY := 33554432
var peer := StreamPeerTCP.new()
var buffer := PackedByteArray()
var connected := false
var retry_at := 0.0
var pending := false
var pending_since := 0.0
var port := 7861
var expected_header := -1
var header: Dictionary = {}
var expected_body := -1

func reset() -> void:
    peer.disconnect_from_host()
    connected = false
    pending = false
    buffer.clear()
    expected_header = -1
    expected_body = -1
    header.clear()
    retry_at = Time.get_ticks_msec() / 1000.0 + 2.0
    connection_changed.emit(false)

func tick() -> void:
    peer.poll()
    var status := peer.get_status()
    if status == StreamPeerTCP.STATUS_CONNECTED:
        if not connected:
            connected = true
            peer.set_no_delay(true)
            connection_changed.emit(true)
        var available := peer.get_available_bytes()
        if available > 0:
            var chunk := peer.get_data(available)
            if chunk[0] != OK:
                reset()
                return
            buffer.append_array(chunk[1])
        if buffer.size() > MAX_BODY + MAX_HEADER + 4:
            reset()
            return
        _parse()
        if pending and Time.get_ticks_msec() / 1000.0 - pending_since > 90.0:
            reset()
    elif status == StreamPeerTCP.STATUS_NONE or status == StreamPeerTCP.STATUS_ERROR:
        if connected:
            reset()
        if Time.get_ticks_msec() / 1000.0 > retry_at:
            retry_at = Time.get_ticks_msec() / 1000.0 + 2.0
            peer.disconnect_from_host()
            peer.connect_to_host("127.0.0.1", port)

func send_image(meta: Dictionary, image: Image) -> bool:
    if not connected or pending:
        return false
    var bytes := image.save_png_to_buffer()
    meta["blobs"] = {"image": bytes.size()}
    var json := JSON.stringify(meta).to_utf8_buffer()
    var packet := PackedByteArray()
    var size := json.size()
    packet.append((size >> 24) & 255)
    packet.append((size >> 16) & 255)
    packet.append((size >> 8) & 255)
    packet.append(size & 255)
    packet.append_array(json)
    packet.append_array(bytes)
    if peer.put_data(packet) != OK:
        reset()
        return false
    pending = true
    pending_since = Time.get_ticks_msec() / 1000.0
    return true

func _parse() -> void:
    while true:
        if expected_header == -1:
            if buffer.size() < 4:
                return
            expected_header = (int(buffer[0]) << 24) | (int(buffer[1]) << 16) | (int(buffer[2]) << 8) | int(buffer[3])
            buffer = buffer.slice(4)
            if expected_header <= 0 or expected_header > MAX_HEADER:
                reset()
                return
        if expected_body == -1:
            if buffer.size() < expected_header:
                return
            var decoded = JSON.parse_string(buffer.slice(0, expected_header).get_string_from_utf8())
            buffer = buffer.slice(expected_header)
            if not decoded is Dictionary or not decoded.get("blobs", {}) is Dictionary:
                reset()
                return
            header = decoded
            expected_body = 0
            for value in header.get("blobs", {}).values():
                if not (value is float or value is int) or value < 0 or value != floor(value):
                    reset()
                    return
                expected_body += int(value)
                if expected_body > MAX_BODY:
                    reset()
                    return
        if buffer.size() < expected_body:
            return
        var blobs := {}
        var cursor := 0
        for key in header.get("blobs", {}):
            var count := int(header["blobs"][key])
            blobs[key] = buffer.slice(cursor, cursor + count)
            cursor += count
        buffer = buffer.slice(expected_body)
        var result := header.duplicate()
        expected_header = -1
        expected_body = -1
        header.clear()
        pending = false
        result_received.emit(result, blobs)
