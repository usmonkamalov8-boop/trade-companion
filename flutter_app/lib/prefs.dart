import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'api.dart';

const kindLabels = {
  'position': 'Positions opened and closed',
  'trade': 'Bot trades and signals',
  'command': 'Halt, Resume, Close all',
  'service': 'Bot service status',
  'warning': 'Warnings (liquidation, API problems)',
  'news': 'Red-folder news alerts',
  'risk': 'Risk changes',
  'profile': 'Profile on / off',
  'system': 'System messages',
};

/// Preferences that live on this phone (pop-up banners).
class LocalPrefs extends ChangeNotifier {
  LocalPrefs._();
  static final LocalPrefs I = LocalPrefs._();

  bool toasts = true;
  final Set<String> kinds = {'position', 'trade', 'command', 'service', 'warning', 'news'};

  Future<void> load() async {
    final sp = await SharedPreferences.getInstance();
    toasts = sp.getBool('toasts') ?? true;
    final k = sp.getStringList('toast_kinds');
    if (k != null) {
      kinds
        ..clear()
        ..addAll(k);
    }
  }

  Future<void> setToasts(bool v) async {
    toasts = v;
    notifyListeners();
    final sp = await SharedPreferences.getInstance();
    await sp.setBool('toasts', v);
  }

  Future<void> setKind(String kind, bool on) async {
    if (on) {
      kinds.add(kind);
    } else {
      kinds.remove(kind);
    }
    notifyListeners();
    final sp = await SharedPreferences.getInstance();
    await sp.setStringList('toast_kinds', kinds.toList());
  }

  bool allows(String kind, String level) => toasts && (kinds.contains(kind) || level == 'error');
}

/// Preferences stored on the server (push categories, calendar alerts, analyst).
/// The backend applies them, so they also work while the app is closed.
class ServerPrefs extends ChangeNotifier {
  ServerPrefs._();
  static final ServerPrefs I = ServerPrefs._();

  Map<String, dynamic> data = {};
  bool loaded = false;
  String? err;

  Future<void> load() async {
    if (!Api.ready) return;
    try {
      data = Map<String, dynamic>.from(await Api.get('/api/prefs') as Map);
      loaded = true;
      err = null;
    } catch (e) {
      err = '$e';
    }
    notifyListeners();
  }

  Map<String, dynamic> section(String name) => (data[name] as Map?)?.cast<String, dynamic>() ?? {};

  Future<void> update(Map<String, dynamic> patch) async {
    _merge(data, patch); // instant feedback
    notifyListeners();
    try {
      data = Map<String, dynamic>.from(await Api.post('/api/prefs', patch) as Map);
      err = null;
    } catch (e) {
      err = '$e';
      await load();
      return;
    }
    notifyListeners();
  }

  static void _merge(Map<String, dynamic> base, Map<String, dynamic> patch) {
    patch.forEach((k, v) {
      if (v is Map && base[k] is Map) {
        _merge((base[k] as Map).cast<String, dynamic>(), v.cast<String, dynamic>());
      } else {
        base[k] = v;
      }
    });
  }
}
