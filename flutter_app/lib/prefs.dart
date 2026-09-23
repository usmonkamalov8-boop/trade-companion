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
  'setup': 'New trade setups and zone alerts',
  'digest': 'Weekly digest',
  'risk': 'Risk changes',
  'profile': 'Profile on / off',
  'system': 'System messages',
};

/// Preferences that live on this phone (pop-up banners).
class LocalPrefs extends ChangeNotifier {
  LocalPrefs._();
  static final LocalPrefs I = LocalPrefs._();

  bool toasts = true;
  final Set<String> kinds = {'position', 'trade', 'command', 'service', 'warning', 'news', 'setup'};

  // Chart layer toggles (Markets > Screener chart): persisted locally, shared by every chart the app shows -
  // stays as set across timeframes, assets, and app restarts until the user changes it again.
  bool chartShowOB = true;
  bool chartShowFvg = true;
  bool chartShowStructure = true;

  bool chartShowTested = true;

  // User-added coins (Markets > Screener "Add coin"): a local mirror of what the server has confirmed and
  // persisted, kept in sync on every add/remove so it survives app restarts even without a network call.
  Set<String> customSymbols = {};

  // Security (Settings > Security): both default on. biometricLock gets out of the way on its own if the
  // device has no usable authentication at all - see AuthGate.
  bool biometricLock = true;
  bool screenProtection = true;

  Future<void> load() async {
    final sp = await SharedPreferences.getInstance();
    toasts = sp.getBool('toasts') ?? true;
    chartShowOB = sp.getBool('chart_show_ob') ?? true;
    chartShowFvg = sp.getBool('chart_show_fvg') ?? true;
    chartShowStructure = sp.getBool('chart_show_structure') ?? true;
    chartShowTested = sp.getBool('chart_show_tested') ?? true;
    customSymbols = (sp.getStringList('custom_symbols') ?? []).toSet();
    biometricLock = sp.getBool('biometric_lock') ?? true;
    screenProtection = sp.getBool('screen_protection') ?? true;
    final k = sp.getStringList('toast_kinds');
    if (k != null) {
      kinds
        ..clear()
        ..addAll(k);
      if (!(sp.getBool('toast_setup_added') ?? false)) {
        kinds.add('setup'); // setup alerts arrived with an update: switch them on once
        await sp.setBool('toast_setup_added', true);
        await sp.setStringList('toast_kinds', kinds.toList());
      }
    }
  }

  Future<void> setChartLayer(String layer, bool v) async {
    final sp = await SharedPreferences.getInstance();
    switch (layer) {
      case 'ob':
        chartShowOB = v;
        await sp.setBool('chart_show_ob', v);
        break;
      case 'fvg':
        chartShowFvg = v;
        await sp.setBool('chart_show_fvg', v);
        break;
      case 'structure':
        chartShowStructure = v;
        await sp.setBool('chart_show_structure', v);
        break;
      case 'tested':
        chartShowTested = v;
        await sp.setBool('chart_show_tested', v);
        break;
    }
    notifyListeners();
  }

  Future<void> setBiometricLock(bool v) async {
    biometricLock = v;
    final sp = await SharedPreferences.getInstance();
    await sp.setBool('biometric_lock', v);
    notifyListeners();
  }

  Future<void> setScreenProtection(bool v) async {
    screenProtection = v;
    final sp = await SharedPreferences.getInstance();
    await sp.setBool('screen_protection', v);
    notifyListeners();
  }

  Future<void> setCustomSymbols(Set<String> v) async {
    customSymbols = v;
    final sp = await SharedPreferences.getInstance();
    await sp.setStringList('custom_symbols', v.toList());
    notifyListeners();
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

/// Time zone used for every clock the app shows. "Automatic" follows this phone; otherwise the zone chosen in
/// Settings (the server tells us its current UTC offset, so no time zone database is needed here).
class TzClock {
  static bool auto = true;
  static int? serverOffset;

  static int get offset =>
      auto ? DateTime.now().timeZoneOffset.inMinutes : (serverOffset ?? DateTime.now().timeZoneOffset.inMinutes);

  static DateTime dt(double ts) =>
      DateTime.fromMillisecondsSinceEpoch((ts * 1000).round(), isUtc: true).add(Duration(minutes: offset));

  static DateTime now() => DateTime.now().toUtc().add(Duration(minutes: offset));

  static String two(int n) => n.toString().padLeft(2, '0');

  static String hm(double ts) {
    final d = dt(ts);
    return '${two(d.hour)}:${two(d.minute)}';
  }
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
      _applyTz();
    } catch (e) {
      err = '$e';
    }
    notifyListeners();
  }

  /// Follows the time zone setting; in automatic mode tells the server this phone's UTC offset.
  void _applyTz() {
    final g = section('general');
    TzClock.auto = g['timezone'] == 'auto';
    TzClock.serverOffset = (g['tz_offset_now'] as num?)?.toInt();
    final dev = DateTime.now().timeZoneOffset.inMinutes;
    if (TzClock.auto && g['tz_offset_min'] != dev) {
      Api.post('/api/prefs', {'general': {'timezone': 'auto', 'tz_offset_min': dev}}).then((r) {
        data = Map<String, dynamic>.from(r as Map);
        notifyListeners();
      }).catchError((_) {});
    }
  }

  Map<String, dynamic> section(String name) => (data[name] as Map?)?.cast<String, dynamic>() ?? {};

  Future<void> update(Map<String, dynamic> patch) async {
    _merge(data, patch); // instant feedback
    notifyListeners();
    try {
      data = Map<String, dynamic>.from(await Api.post('/api/prefs', patch) as Map);
      err = null;
      final g = section('general');
      TzClock.auto = g['timezone'] == 'auto';
      TzClock.serverOffset = (g['tz_offset_now'] as num?)?.toInt();
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
