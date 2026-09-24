import 'dart:convert';
import 'package:crypto/crypto.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Local PIN storage. Only a salted SHA-256 hash is ever stored - the PIN itself never touches disk.
class PinService {
  PinService._();
  static final PinService I = PinService._();

  static const _hashKey = 'pin_hash';
  static const _saltKey = 'pin_salt';

  Future<bool> hasPin() async {
    final p = await SharedPreferences.getInstance();
    return p.getString(_hashKey) != null;
  }

  String _hash(String pin, String salt) => sha256.convert(utf8.encode('$salt:$pin')).toString();

  Future<void> setPin(String pin) async {
    final p = await SharedPreferences.getInstance();
    final salt = '${DateTime.now().microsecondsSinceEpoch}';
    await p.setString(_saltKey, salt);
    await p.setString(_hashKey, _hash(pin, salt));
  }

  Future<bool> verifyPin(String pin) async {
    final p = await SharedPreferences.getInstance();
    final salt = p.getString(_saltKey);
    final hash = p.getString(_hashKey);
    if (salt == null || hash == null) return false;
    return _hash(pin, salt) == hash;
  }

  Future<void> clearPin() async {
    final p = await SharedPreferences.getInstance();
    await p.remove(_hashKey);
    await p.remove(_saltKey);
  }
}
