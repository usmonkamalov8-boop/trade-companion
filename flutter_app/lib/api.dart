import 'dart:convert';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

class Api {
  static const _store = FlutterSecureStorage();
  static String host = '185.196.117.48:8000';
  static String token = '';
  static bool get ready => host.isNotEmpty && token.isNotEmpty;

  static Future<void> load() async {
    host = await _store.read(key: 'host') ?? host;
    token = await _store.read(key: 'token') ?? '';
  }

  static Future<void> save(String h, String t) async {
    host = h.trim();
    token = t.trim();
    await _store.write(key: 'host', value: host);
    await _store.write(key: 'token', value: token);
  }

  static Uri _uri(String path, [Map<String, String>? q]) {
    final base = host.startsWith('http') ? host : 'http://$host';
    return Uri.parse('$base$path').replace(queryParameters: q);
  }

  static Map<String, String> get _headers => {
        'Authorization': 'Bearer $token',
        'Content-Type': 'application/json',
      };

  static dynamic _decode(http.Response r) {
    if (r.statusCode == 401) throw Exception('Wrong API token. Check Settings.');
    if (r.statusCode != 200) throw Exception('HTTP ${r.statusCode}: ${r.body}');
    return jsonDecode(utf8.decode(r.bodyBytes));
  }

  static Future<dynamic> get(String path, [Map<String, String>? q]) async =>
      _decode(await http.get(_uri(path, q), headers: _headers).timeout(const Duration(seconds: 40)));

  static Future<dynamic> post(String path, [Object? body]) async => _decode(await http
      .post(_uri(path), headers: _headers, body: jsonEncode(body ?? {}))
      .timeout(const Duration(seconds: 60)));

  static Stream<String> stream(String path,
      {String method = 'GET', Object? body, Map<String, String>? q}) async* {
    final client = http.Client();
    try {
      final req = http.Request(method, _uri(path, q))..headers.addAll(_headers);
      if (body != null) req.body = jsonEncode(body);
      final res = await client.send(req);
      if (res.statusCode == 401) throw Exception('Wrong API token. Check Settings.');
      if (res.statusCode != 200) throw Exception('HTTP ${res.statusCode}');
      yield* res.stream.transform(utf8.decoder);
    } finally {
      client.close();
    }
  }
}
