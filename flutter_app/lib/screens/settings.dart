import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';
import '../api.dart';
import '../calc.dart';
import '../events.dart';
import '../prefs.dart';
import '../theme.dart';

const moduleLabels = {
  'structure': 'Market structure (BOS / CHoCH)',
  'ob': 'Order blocks and breakers',
  'fvg': 'Fair value gaps',
  'sd': 'Supply and demand zones',
  'sr': 'Support and resistance',
  'fib': 'Fibonacci and premium / discount',
  'trend': 'Trendlines, channels, dynamic levels',
  'liquidity': 'Liquidity and sweeps',
  'volume': 'Volume profile (POC, value area) and volume checks',
  'ict': 'ICT context (kill zones, day and week levels)',
};

const styleLabels = {'scalp': 'Scalp', 'intraday': 'Intraday', 'swing': 'Swing'};

Future<void> pushPage(BuildContext context, Widget page) =>
    Navigator.of(context).push(MaterialPageRoute(builder: (_) => page));

/// One place for everything that can be changed in the app.
class SettingsPage extends StatelessWidget {
  const SettingsPage({super.key});

  Widget _tile(BuildContext context, IconData icon, String title, String sub, Widget page) {
    final p = context.pal;
    return Panel(
      padding: EdgeInsets.zero,
      child: ListTile(
        leading: Icon(icon, color: p.accent),
        title: Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Text(sub, style: TextStyle(color: p.muted, fontSize: 12.5)),
        trailing: Icon(Icons.chevron_right, color: p.muted),
        onTap: () => pushPage(context, page),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListenableBuilder(
        listenable: Listenable.merge([ThemeController.I, LocalPrefs.I, ServerPrefs.I]),
        builder: (context, _) {
          final sp = ServerPrefs.I;
          final push = sp.section('push');
          final cal = sp.section('calendar');
          final an = sp.section('analyst');
          final cur = ((cal['currencies'] as List?) ?? []).join(', ');
          return ListView(padding: const EdgeInsets.all(12), children: [
            _tile(context, Icons.wifi_tethering, 'Connection',
                Api.ready ? Api.host : 'Not connected: enter your API token', const ConnectionPage()),
            _tile(context, Icons.palette_outlined, 'Appearance', ThemeController.I.pal.name, const AppearancePage()),
            _tile(
                context,
                Icons.notifications_outlined,
                'Notifications',
                'Pop-ups ${LocalPrefs.I.toasts ? 'on' : 'off'}, push ${push['enabled'] == true ? 'on' : 'off'}',
                const NotificationsPage()),
            _tile(
                context,
                Icons.event_note_outlined,
                'Calendar alerts',
                cal.isEmpty
                    ? 'Red-folder news alerts'
                    : '${cal['alerts'] == true ? 'On' : 'Off'}: ${cal['impact'] == 'medium' ? 'red + orange' : 'red folder'}, $cur',
                const CalendarAlertsPage()),
            _tile(context, Icons.schedule, 'Time zone',
                '${sp.section('general')['tz_title'] ?? 'Automatic (this phone)'}  (${sp.section('general')['tz_label'] ?? ''})',
                const TimeZonePage()),
            _tile(context, Icons.auto_graph, 'AI analyst',
                'Default style: ${styleLabels[an['style']] ?? 'Intraday'}', const AnalystPage()),
            _tile(context, Icons.monitor_heart_outlined, 'Diagnostics', 'Server, live feed, push and calendar status',
                const DiagnosticsPage()),
            _tile(context, Icons.security_outlined, 'Security',
                'App lock ${LocalPrefs.I.biometricLock ? 'on' : 'off'}',
                const SecurityPage()),
            Panel(
              padding: EdgeInsets.zero,
              child: ListTile(
                leading: Icon(Icons.calculate_outlined, color: p.accent),
                title: const Text('Position size calculator', style: TextStyle(fontWeight: FontWeight.w600)),
                subtitle: Text('From account size, risk % and stop distance', style: TextStyle(color: p.muted, fontSize: 12.5)),
                trailing: Icon(Icons.chevron_right, color: p.muted),
                onTap: () => showPositionCalc(context),
              ),
            ),
            const SizedBox(height: 8),
            Text('Trade Companion. Analysis is rule-based and is not financial advice.',
                textAlign: TextAlign.center, style: TextStyle(color: p.muted, fontSize: 12)),
          ]);
        },
      ),
    );
  }
}

// ------------------------------------------------------------------ connection

class ConnectionPage extends StatefulWidget {
  const ConnectionPage({super.key});
  @override
  State<ConnectionPage> createState() => _ConnectionPageState();
}

class _ConnectionPageState extends State<ConnectionPage> {
  final host = TextEditingController(text: Api.host);
  final token = TextEditingController(text: Api.token);
  bool hide = true;
  String result = '';
  bool ok = false;

  Future<void> _save() async {
    await Api.save(host.text, token.text);
    EventService.I.restart();
    ServerPrefs.I.load();
    if (mounted) {
      setState(() {
        ok = true;
        result = 'Saved.';
      });
    }
  }

  Future<void> _test() async {
    await _save();
    try {
      await Api.get('/api/status'); // confirms the Companion API itself answers
      String extra = '';
      try {
        final t = await Api.get('/api/trade/status') as Map<String, dynamic>;
        extra = ' Trading engine: ${t['env']}${t['armed'] == true ? ' (armed)' : ''}'
            '${t['halted'] == true ? ', new entries stopped' : ''}.';
      } catch (_) {
        extra = ' Trading engine (tcexec) not reachable.';
      }
      if (mounted) {
        setState(() {
          ok = true;
          result = 'Connected.$extra';
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          ok = false;
          result = 'Could not connect: $e';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    return Scaffold(
      appBar: AppBar(title: const Text('Connection')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        TextField(
          controller: host,
          keyboardType: TextInputType.url,
          decoration: const InputDecoration(labelText: 'VPS address (IP:port)', border: OutlineInputBorder()),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: token,
          obscureText: hide,
          decoration: InputDecoration(
            labelText: 'API token',
            border: const OutlineInputBorder(),
            suffixIcon: IconButton(
              icon: Icon(hide ? Icons.visibility : Icons.visibility_off),
              onPressed: () => setState(() => hide = !hide),
            ),
          ),
        ),
        const SizedBox(height: 16),
        Row(children: [
          Expanded(child: OutlinedButton(onPressed: _save, child: const Text('Save'))),
          const SizedBox(width: 8),
          Expanded(child: FilledButton(onPressed: _test, child: const Text('Save and test'))),
        ]),
        const SizedBox(height: 12),
        if (result.isNotEmpty) Panel(child: Text(result, style: TextStyle(color: ok ? p.gain : p.loss))),
        const SizedBox(height: 8),
        Panel(
          child: Text(
            host.text.trim().replaceAll('http://', '').startsWith('100.')
                ? 'This is a Tailscale address: traffic is encrypted end to end, and once the server is locked (tc_tailscale.py lock) '
                    'the API cannot be reached from the internet at all.'
                : 'This is a public address: anyone on the internet can try to reach the API, and traffic is plain HTTP. '
                    'Safer: install Tailscale on the VPS and this phone and use the 100.x.y.z address (run tc_tailscale.py setup on the VPS).',
            style: TextStyle(
                color: host.text.trim().replaceAll('http://', '').startsWith('100.') ? p.gain : p.warn, fontSize: 12.5, height: 1.4),
          ),
        ),
        const SizedBox(height: 8),
        Text(
          'The token is stored privately inside this app. Keep it private either way.',
          style: TextStyle(color: p.muted, fontSize: 12.5, height: 1.4),
        ),
      ]),
    );
  }
}

// ------------------------------------------------------------------ appearance

class AppearancePage extends StatelessWidget {
  const AppearancePage({super.key});

  Widget _swatch(Pal x) => Row(mainAxisSize: MainAxisSize.min, children: [
        for (final c in [x.bg, x.surface, x.accent, x.gain, x.loss])
          Container(
            width: 18,
            height: 18,
            margin: const EdgeInsets.only(right: 5),
            decoration: BoxDecoration(color: c, shape: BoxShape.circle, border: Border.all(color: x.outline)),
          ),
      ]);

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Appearance')),
      body: ListenableBuilder(
        listenable: ThemeController.I,
        builder: (context, _) {
          final current = ThemeController.I.id;
          return ListView(padding: const EdgeInsets.all(16), children: [
            for (final x in palettes)
              GestureDetector(
                onTap: () => ThemeController.I.select(x.id),
                child: Container(
                  margin: const EdgeInsets.only(bottom: 10),
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: x.surface,
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: current == x.id ? x.accent : x.outline, width: current == x.id ? 2 : 1),
                  ),
                  child: Row(children: [
                    Expanded(
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text(x.name, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 16)),
                        const SizedBox(height: 10),
                        _swatch(x),
                      ]),
                    ),
                    if (current == x.id) Icon(Icons.check_circle, color: x.accent),
                  ]),
                ),
              ),
          ]);
        },
      ),
    );
  }
}

// --------------------------------------------------------------- notifications

class SecurityPage extends StatelessWidget {
  const SecurityPage({super.key});

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    return Scaffold(
      appBar: AppBar(title: const Text('Security')),
      body: ListenableBuilder(
        listenable: LocalPrefs.I,
        builder: (context, _) {
          final lp = LocalPrefs.I;
          return ListView(padding: const EdgeInsets.all(12), children: [
            const Heading('App lock'),
            Panel(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                SwitchListTile(
                  title: const Text('Require unlock to open the app'),
                  subtitle: Text('Fingerprint, Face ID, or your device PIN/pattern - on launch and whenever the app returns from the background.',
                      style: TextStyle(color: p.muted, fontSize: 12.5)),
                  value: lp.biometricLock,
                  onChanged: lp.setBiometricLock,
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                  child: Text(
                    'If this phone has no fingerprint/face unlock or PIN set up at all, the app opens normally either way - it never locks you out of your own account.',
                    style: TextStyle(color: p.muted, fontSize: 11.5),
                  ),
                ),
              ]),
            ),
          ]);
        },
      ),
    );
  }
}

class NotificationsPage extends StatefulWidget {
  const NotificationsPage({super.key});
  @override
  State<NotificationsPage> createState() => _NotificationsPageState();
}

class _NotificationsPageState extends State<NotificationsPage> {
  Map<String, dynamic>? info;
  String msg = '';
  bool ok = true;

  @override
  void initState() {
    super.initState();
    ServerPrefs.I.load();
    _info();
  }

  Future<void> _info() async {
    if (!Api.ready) return;
    try {
      final d = await Api.get('/api/push/info') as Map<String, dynamic>;
      if (mounted) setState(() => info = d);
    } catch (e) {
      if (mounted) setState(() => msg = 'Push status unavailable: $e');
    }
  }

  Future<void> _testPush() async {
    try {
      await Api.post('/api/push/test');
      if (mounted) {
        setState(() {
          ok = true;
          msg = 'Test push sent. Close the app and check that the ntfy notification arrives.';
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          ok = false;
          msg = '$e';
        });
      }
    }
  }

  Future<void> _testProvider(String provider) async {
    try {
      await Api.post('/api/push/test?priority=3&provider=$provider');
      if (mounted) {
        setState(() {
          ok = true;
          msg = 'Test sent through $provider. Close the app and check your phone.';
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          ok = false;
          msg = '$e';
        });
      }
    }
    _info();
  }

  String _provLine(String name, Map? v, String setupHint) {
    if (v == null || v['configured'] != true) return '$name: not set up. $setupHint';
    final until = ((v['paused_until'] as num?) ?? 0).toInt();
    final sent = 'sent today: ${v['sent_today'] ?? 0}';
    if (until > 0) {
      final d = DateTime.fromMillisecondsSinceEpoch(until * 1000, isUtc: true);
      final hm = '${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')} UTC';
      return '$name: PAUSED until $hm ($sent). ${v['error'] ?? ''}';
    }
    return '$name: working ($sent)${v['error'] != null ? '. Last error: ${v['error']}' : ''}';
  }

  Future<void> _testLevel(int level) async {
    try {
      await Api.post('/api/push/test?priority=$level');
      if (mounted) {
        setState(() {
          ok = true;
          msg = 'Test push sent at level $level. Close the app to hear the ntfy sound.';
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          ok = false;
          msg = '$e';
        });
      }
    }
  }

  Future<void> _pickTime(String key, String current) async {
    final parts = current.split(':');
    final t = await showTimePicker(
      context: context,
      initialTime: TimeOfDay(hour: int.tryParse(parts[0]) ?? 23, minute: int.tryParse(parts.length > 1 ? parts[1] : '0') ?? 0),
      builder: (c, w) => MediaQuery(data: MediaQuery.of(c).copyWith(alwaysUse24HourFormat: true), child: w!),
    );
    if (t == null) return;
    final v = '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
    await ServerPrefs.I.update({'setups': {'quiet': {key: v}}});
  }

  Future<void> _readDigest() async {
    try {
      final d = await Api.get('/api/digest') as Map<String, dynamic>;
      if (!mounted) return;
      showDialog(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Weekly digest'),
          content: SingleChildScrollView(child: SelectableText('${d['text']}', style: const TextStyle(fontSize: 13, height: 1.4))),
          actions: [TextButton(onPressed: () => Navigator.pop(c), child: const Text('Close'))],
        ),
      );
    } catch (e) {
      if (mounted) {
        setState(() {
          ok = false;
          msg = '$e';
        });
      }
    }
  }

  Future<void> _sendDigest() async {
    try {
      await Api.post('/api/digest/send');
      if (mounted) {
        setState(() {
          ok = true;
          msg = 'Digest sent. It appears in Activity and arrives as a silent push.';
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          ok = false;
          msg = '$e';
        });
      }
    }
  }

  Future<void> _testSetup() async {
    try {
      await Api.post('/api/setups/test');
      if (mounted) {
        setState(() {
          ok = true;
          msg = 'Test setup alert sent. A pop-up (and push, if enabled) should arrive.';
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          ok = false;
          msg = '$e';
        });
      }
    }
  }

  Future<void> _copy(String topic) async {
    await Clipboard.setData(ClipboardData(text: topic));
    if (mounted) {
      setState(() {
        ok = true;
        msg = 'Topic copied. Paste it into the ntfy app.';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    return Scaffold(
      appBar: AppBar(title: const Text('Notifications')),
      body: ListenableBuilder(
        listenable: Listenable.merge([LocalPrefs.I, ServerPrefs.I]),
        builder: (context, _) {
          final lp = LocalPrefs.I;
          final push = ServerPrefs.I.section('push');
          final kinds = (push['kinds'] as Map?)?.cast<String, dynamic>() ?? {};
          final pushOn = push['enabled'] == true;
          final setupsCfg = ServerPrefs.I.section('setups');
          final soundCfg = (setupsCfg['sound'] as Map?)?.cast<String, dynamic>() ?? {};
          final quietCfg = (setupsCfg['quiet'] as Map?)?.cast<String, dynamic>() ?? {};
          final digestCfg = ServerPrefs.I.section('digest');
          final setupStyles = ((setupsCfg['styles'] as List?) ?? ['scalp', 'intraday', 'swing']).map((e) => '$e').toList();
          final setupMarkets = ((setupsCfg['markets'] as List?) ?? ['crypto', 'forex']).map((e) => '$e').toList();
          final topic = info != null && info!['topic'] != null ? '${info!['topic']}' : '';
          final configured = info != null && info!['configured'] == true;
          return ListView(padding: const EdgeInsets.all(12), children: [
            const Heading('Pop-ups while the app is open'),
            Panel(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Column(children: [
                SwitchListTile(
                  title: const Text('Show pop-up banners'),
                  value: lp.toasts,
                  onChanged: lp.setToasts,
                ),
                for (final e in kindLabels.entries)
                  SwitchListTile(
                    dense: true,
                    title: Text(e.value),
                    value: lp.kinds.contains(e.key),
                    onChanged: lp.toasts ? (v) => lp.setKind(e.key, v) : null,
                  ),
              ]),
            ),
            const Heading('Trade setup alerts'),
            Panel(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                SwitchListTile(
                  title: const Text('Alert when a new setup appears'),
                  subtitle: Text('Sent as soon as the server finds it, before price reaches the zone',
                      style: TextStyle(color: p.muted, fontSize: 12.5)),
                  value: setupsCfg['enabled'] == true,
                  onChanged: (v) => ServerPrefs.I.update({'setups': {'enabled': v}}),
                ),
                SwitchListTile(
                  dense: true,
                  title: const Text('Also alert when price reaches the zone or it is READY'),
                  value: setupsCfg['on_zone'] == true,
                  onChanged: setupsCfg['enabled'] == true ? (v) => ServerPrefs.I.update({'setups': {'on_zone': v}}) : null,
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
                  child: Text('Minimum confidence: ${setupsCfg['min_conf'] ?? 50}', style: TextStyle(color: p.muted, fontSize: 12.5)),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 4, 16, 0),
                  child: Wrap(spacing: 8, children: [
                    for (final c in [0, 40, 50, 60, 70, 80])
                      ChoiceChip(
                        label: Text(c == 0 ? 'Any' : '$c+'),
                        selected: (setupsCfg['min_conf'] as num?)?.toInt() == c,
                        onSelected: (_) => ServerPrefs.I.update({'setups': {'min_conf': c}}),
                      ),
                  ]),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 10, 16, 0),
                  child: Wrap(spacing: 8, children: [
                    for (final e in styleLabels.entries)
                      FilterChip(
                        label: Text(e.value),
                        selected: setupStyles.contains(e.key),
                        onSelected: (v) {
                          final next = [...setupStyles];
                          if (v) {
                            next.add(e.key);
                          } else if (next.length > 1) {
                            next.remove(e.key);
                          }
                          ServerPrefs.I.update({'setups': {'styles': next}});
                        },
                      ),
                    for (final e in const {'crypto': 'Crypto', 'forex': 'Forex and gold'}.entries)
                      FilterChip(
                        label: Text(e.value),
                        selected: setupMarkets.contains(e.key),
                        onSelected: (v) {
                          final next = [...setupMarkets];
                          if (v) {
                            next.add(e.key);
                          } else if (next.length > 1) {
                            next.remove(e.key);
                          }
                          ServerPrefs.I.update({'setups': {'markets': next}});
                        },
                      ),
                  ]),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 10, 16, 0),
                  child: Text('Only alert if the zone is within: ${(setupsCfg['max_dist_atr'] as num?) == 0 ? 'any distance' : '${setupsCfg['max_dist_atr'] ?? 3} ATR (or price is already in it)'}',
                      style: TextStyle(color: p.muted, fontSize: 12.5)),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 4, 16, 0),
                  child: Wrap(spacing: 8, children: [
                    for (final v in [0, 1, 2, 3, 5])
                      ChoiceChip(
                        label: Text(v == 0 ? 'Any' : '$v ATR'),
                        selected: ((setupsCfg['max_dist_atr'] as num?)?.toInt() ?? 3) == v,
                        onSelected: (_) => ServerPrefs.I.update({'setups': {'max_dist_atr': v}}),
                      ),
                  ]),
                ),
                SwitchListTile(
                  dense: true,
                  title: const Text('Wait for the candle close before alerting'),
                  subtitle: Text('Fewer false alerts: setups that vanish before their candle closes are dropped, but the alert comes later',
                      style: TextStyle(color: p.muted, fontSize: 12)),
                  value: setupsCfg['confirm_close'] == true,
                  onChanged: (v) => ServerPrefs.I.update({'setups': {'confirm_close': v}}),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 6, 16, 0),
                  child: Text('How often the server looks for setups', style: TextStyle(color: p.muted, fontSize: 12.5)),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
                  child: SegmentedButton<int>(
                    segments: const [
                      ButtonSegment(value: 60, label: Text('1 min')),
                      ButtonSegment(value: 120, label: Text('2 min')),
                      ButtonSegment(value: 300, label: Text('5 min')),
                    ],
                    selected: {[60, 120, 300].contains((setupsCfg['scan_seconds'] as num?)?.toInt()) ? (setupsCfg['scan_seconds'] as num).toInt() : 60},
                    onSelectionChanged: (s) => ServerPrefs.I.update({'setups': {'scan_seconds': s.first}}),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                  child: Text(
                    'Needs "Send push notifications" below and the "New trade setups" category to be on. '
                    'Phone pop-ups use the pop-up list above.',
                    style: TextStyle(color: p.muted, fontSize: 12, height: 1.4),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                  child: OutlinedButton.icon(
                    onPressed: _testSetup,
                    icon: const Icon(Icons.notifications_active_outlined, size: 18),
                    label: const Text('Send a test setup alert'),
                  ),
                ),
              ]),
            ),
            const Heading('Alert loudness by confidence'),
            Panel(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                SwitchListTile(
                  title: const Text('Louder alerts for stronger setups'),
                  subtitle: Text('Sets the ntfy priority of a setup push from its confidence',
                      style: TextStyle(color: p.muted, fontSize: 12.5)),
                  value: soundCfg['enabled'] != false,
                  onChanged: (v) => ServerPrefs.I.update({'setups': {'sound': {'enabled': v}}}),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 4),
                  child: Text(
                      'Urgent means READY: price is in the zone with confirmation, no news hold, and the confidence is at or above '
                      'the Urgent level below. A setup price has not reached yet is never louder than High.',
                      style: TextStyle(color: p.muted, fontSize: 12, height: 1.4)),
                ),
                for (final row in [
                  ['urgent_from', 'Urgent (loudest) needs confidence of at least', '70', '60,65,70,75,80,85'],
                  ['high_from', 'High from confidence', '60', '50,55,60,65,70'],
                  ['quiet_below', 'Quiet (silent-ish) below confidence', '50', '30,40,50,60'],
                ])
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 4, 16, 4),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text('${row[1]}: ${soundCfg[row[0]] ?? row[2]}', style: TextStyle(color: p.muted, fontSize: 12.5)),
                      Wrap(spacing: 8, children: [
                        for (final v in row[3].split(',').map(int.parse))
                          ChoiceChip(
                            label: Text('$v'),
                            selected: ((soundCfg[row[0]] as num?)?.toInt() ?? int.parse(row[2])) == v,
                            onSelected: (_) => ServerPrefs.I.update({'setups': {'sound': {row[0]: v}}}),
                          ),
                      ]),
                    ]),
                  ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
                  child: Text('Send a test at each level and give each its own sound:', style: TextStyle(color: p.muted, fontSize: 12.5)),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                  child: Wrap(spacing: 8, runSpacing: 4, children: [
                    for (final t in const [
                      [2, 'Quiet'],
                      [3, 'Normal'],
                      [4, 'High'],
                      [5, 'Urgent'],
                    ])
                      OutlinedButton(onPressed: () => _testLevel(t[0] as int), child: Text('${t[1]} (${t[0]})')),
                  ]),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
                  child: Text(
                    'The ntfy app makes one Android notification channel per level. To hear the difference: Android Settings > '
                    'Apps > ntfy > Notifications, open each priority channel and pick a different sound. For Urgent also allow '
                    '"Override Do Not Disturb". The server chooses the level; the sound itself is set on the phone.',
                    style: TextStyle(color: p.muted, fontSize: 12, height: 1.4),
                  ),
                ),
              ]),
            ),
            const Heading('Quiet hours and limits'),
            Panel(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                SwitchListTile(
                  title: const Text('Quiet hours'),
                  subtitle: Text('Setup alerts arrive silently (no sound) in this window, in your time zone (${ServerPrefs.I.section('general')['tz_label'] ?? 'server time'})',
                      style: TextStyle(color: p.muted, fontSize: 12.5)),
                  value: quietCfg['enabled'] == true,
                  onChanged: (v) => ServerPrefs.I.update({'setups': {'quiet': {'enabled': v}}}),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 4),
                  child: Row(children: [
                    Expanded(
                      child: OutlinedButton(
                        onPressed: quietCfg['enabled'] == true ? () => _pickTime('from', '${quietCfg['from'] ?? '23:00'}') : null,
                        child: Text('From ${quietCfg['from'] ?? '23:00'}'),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: OutlinedButton(
                        onPressed: quietCfg['enabled'] == true ? () => _pickTime('to', '${quietCfg['to'] ?? '07:00'}') : null,
                        child: Text('To ${quietCfg['to'] ?? '07:00'}'),
                      ),
                    ),
                  ]),
                ),
                SwitchListTile(
                  dense: true,
                  title: const Text('Let Urgent (READY) alerts through'),
                  subtitle: Text('Off: even Urgent alerts stay silent during quiet hours',
                      style: TextStyle(color: p.muted, fontSize: 12)),
                  value: quietCfg['allow_urgent'] == true,
                  onChanged: quietCfg['enabled'] == true ? (v) => ServerPrefs.I.update({'setups': {'quiet': {'allow_urgent': v}}}) : null,
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
                  child: Text(
                      'Daily limit for loud (High) alerts: ${((setupsCfg['loud_cap'] as num?)?.toInt() ?? 3) == 0 ? 'no limit' : '${(setupsCfg['loud_cap'] as num?)?.toInt() ?? 3} a day'}',
                      style: TextStyle(color: p.muted, fontSize: 12.5)),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 4, 16, 0),
                  child: Wrap(spacing: 8, children: [
                    for (final v in [1, 2, 3, 5, 10, 0])
                      ChoiceChip(
                        label: Text(v == 0 ? 'No limit' : '$v'),
                        selected: ((setupsCfg['loud_cap'] as num?)?.toInt() ?? 3) == v,
                        onSelected: (_) => ServerPrefs.I.update({'setups': {'loud_cap': v}}),
                      ),
                  ]),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 4, 16, 10),
                  child: Text('After the limit, extra High alerts come at Normal loudness. Urgent (READY) alerts always sound outside quiet hours.',
                      style: TextStyle(color: p.muted, fontSize: 12, height: 1.4)),
                ),
              ]),
            ),
            const Heading('Weekly digest'),
            Panel(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                SwitchListTile(
                  title: const Text('Send a weekly summary'),
                  subtitle: Text('Journal results with 95% ranges, repaint rate, hypotheses and backup status. Silent push.',
                      style: TextStyle(color: p.muted, fontSize: 12.5)),
                  value: digestCfg['enabled'] != false,
                  onChanged: (v) => ServerPrefs.I.update({'digest': {'enabled': v}}),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 4),
                  child: Wrap(spacing: 6, children: [
                    for (var d = 0; d < 7; d++)
                      ChoiceChip(
                        label: Text(const ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][d]),
                        selected: ((digestCfg['day'] as num?)?.toInt() ?? 6) == d,
                        onSelected: (_) => ServerPrefs.I.update({'digest': {'day': d}}),
                      ),
                  ]),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 4, 16, 0),
                  child: Text('At ${((digestCfg['hour'] as num?)?.toInt() ?? 18).toString().padLeft(2, '0')}:00 your time', style: TextStyle(color: p.muted, fontSize: 12.5)),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 4, 16, 0),
                  child: Wrap(spacing: 6, children: [
                    for (final h in [8, 12, 18, 20, 21])
                      ChoiceChip(
                        label: Text('$h:00'),
                        selected: ((digestCfg['hour'] as num?)?.toInt() ?? 18) == h,
                        onSelected: (_) => ServerPrefs.I.update({'digest': {'hour': h}}),
                      ),
                  ]),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 10),
                  child: Row(children: [
                    Expanded(child: OutlinedButton(onPressed: _readDigest, child: const Text('Read it now'))),
                    const SizedBox(width: 8),
                    Expanded(child: OutlinedButton(onPressed: _sendDigest, child: const Text('Send it now'))),
                  ]),
                ),
              ]),
            ),
            const Heading('Push notifications (app closed)'),
            Panel(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Column(children: [
                SwitchListTile(
                  title: const Text('Send push notifications'),
                  subtitle: Text(
                    configured ? 'Delivered by the free ntfy app' : 'Not configured on the server (no topic)',
                    style: TextStyle(color: p.muted, fontSize: 12.5),
                  ),
                  value: pushOn,
                  onChanged: (v) => ServerPrefs.I.update({'push': {'enabled': v}}),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
                  child: SegmentedButton<String>(
                    segments: const [
                      ButtonSegment(value: 'full', label: Text('Full details')),
                      ButtonSegment(value: 'minimal', label: Text('Minimal text')),
                    ],
                    selected: {push['detail'] == 'minimal' ? 'minimal' : 'full'},
                    onSelectionChanged: (s) => ServerPrefs.I.update({'push': {'detail': s.first}}),
                  ),
                ),
                for (final e in kindLabels.entries)
                  SwitchListTile(
                    dense: true,
                    title: Text(e.value),
                    value: kinds[e.key] == true,
                    onChanged: pushOn ? (v) => ServerPrefs.I.update({'push': {'kinds': {e.key: v}}}) : null,
                  ),
              ]),
            ),
            const Heading('Delivery route'),
            Panel(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(
                    'The free ntfy.sh server allows 250 messages a day per server IP and then answers 429. With a Telegram bot as a second '
                    'route, alerts keep arriving.',
                    style: TextStyle(color: p.muted, fontSize: 12.5, height: 1.4)),
                const SizedBox(height: 8),
                Wrap(spacing: 8, children: [
                  for (final r in const [
                    ['auto', 'Auto'],
                    ['ntfy', 'ntfy only'],
                    ['telegram', 'Telegram only'],
                    ['both', 'Both'],
                  ])
                    ChoiceChip(
                      label: Text(r[1]),
                      selected: (push['route'] ?? 'auto') == r[0],
                      onSelected: (_) => ServerPrefs.I.update({'push': {'route': r[0]}}),
                    ),
                ]),
                const SizedBox(height: 4),
                Text(
                    (push['route'] ?? 'auto') == 'auto'
                        ? 'Auto: ntfy first; Telegram whenever ntfy fails or is paused.'
                        : ((push['route'] == 'both') ? 'Both: every alert goes to ntfy and to Telegram.' : 'Only ${push['route']} is used.'),
                    style: TextStyle(color: p.muted, fontSize: 12)),
                const SizedBox(height: 8),
                Text(_provLine('ntfy', (info?['providers'] as Map?)?['ntfy'] as Map?, 'Set NTFY_TOPIC in backend/.env.'),
                    style: TextStyle(fontSize: 12.5, color: (((info?['providers'] as Map?)?['ntfy'] as Map?)?['paused_until'] ?? 0) != 0 ? p.warn : p.muted)),
                const SizedBox(height: 4),
                Text(_provLine('Telegram', (info?['providers'] as Map?)?['telegram'] as Map?, 'On the VPS run: python3 ~/tc_push.py telegram'),
                    style: TextStyle(fontSize: 12.5, color: (((info?['providers'] as Map?)?['telegram'] as Map?)?['paused_until'] ?? 0) != 0 ? p.warn : p.muted)),
                const SizedBox(height: 8),
                Row(children: [
                  Expanded(child: OutlinedButton(onPressed: () => _testProvider('ntfy'), child: const Text('Test ntfy'))),
                  const SizedBox(width: 8),
                  Expanded(child: OutlinedButton(onPressed: () => _testProvider('telegram'), child: const Text('Test Telegram'))),
                ]),
              ]),
            ),
            Panel(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Your private topic', style: TextStyle(color: p.muted, fontSize: 12)),
                Row(children: [
                  Expanded(
                    child: SelectableText(topic.isEmpty ? '-' : topic, style: numStyle.copyWith(fontWeight: FontWeight.w600)),
                  ),
                  IconButton(onPressed: topic.isEmpty ? null : () => _copy(topic), icon: const Icon(Icons.copy)),
                ]),
                Text(
                  '1. Install the free ntfy app.  2. In ntfy tap +, paste the topic, subscribe.  '
                  '3. Allow notifications for ntfy and set its battery use to "No restrictions".',
                  style: TextStyle(color: p.muted, fontSize: 12.5, height: 1.4),
                ),
                const SizedBox(height: 10),
                Row(children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: () => launchUrl(
                        Uri.parse('https://play.google.com/store/apps/details?id=io.heckel.ntfy'),
                        mode: LaunchMode.externalApplication,
                      ),
                      child: const Text('Get ntfy app'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(child: FilledButton(onPressed: configured ? _testPush : null, child: const Text('Send test push'))),
                ]),
              ]),
            ),
            if (msg.isNotEmpty) Panel(child: Text(msg, style: TextStyle(color: ok ? p.gain : p.loss))),
            if (ServerPrefs.I.err != null)
              Panel(child: Text('Could not reach the server: ${ServerPrefs.I.err}', style: TextStyle(color: p.loss))),
          ]);
        },
      ),
    );
  }
}

// ------------------------------------------------------------ calendar alerts

class CalendarAlertsPage extends StatefulWidget {
  const CalendarAlertsPage({super.key});
  @override
  State<CalendarAlertsPage> createState() => _CalendarAlertsPageState();
}

class _CalendarAlertsPageState extends State<CalendarAlertsPage> {
  String msg = '';
  bool ok = true;
  static const currencies = ['USD', 'EUR', 'GBP', 'JPY', 'AUD', 'CAD', 'CHF', 'NZD'];
  static const leads = {120: '2 h', 60: '1 h', 30: '30 min', 15: '15 min', 5: '5 min', 0: 'At release'};

  @override
  void initState() {
    super.initState();
    ServerPrefs.I.load();
  }

  Future<void> _call(String path, String okText) async {
    try {
      await Api.post(path);
      if (mounted) {
        setState(() {
          ok = true;
          msg = okText;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          ok = false;
          msg = '$e';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    return Scaffold(
      appBar: AppBar(title: const Text('Calendar alerts')),
      body: ListenableBuilder(
        listenable: ServerPrefs.I,
        builder: (context, _) {
          final cal = ServerPrefs.I.section('calendar');
          final cur = ((cal['currencies'] as List?) ?? ['USD']).map((e) => '$e').toList();
          final ld = ((cal['leads'] as List?) ?? [60, 15, 0]).map((e) => (e as num).toInt()).toList();
          final on = cal['alerts'] == true;
          return ListView(padding: const EdgeInsets.all(12), children: [
            Panel(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: SwitchListTile(
                title: const Text('Alert before high-impact news'),
                subtitle: Text('Pop-up in the app and, if enabled, a push notification',
                    style: TextStyle(color: p.muted, fontSize: 12.5)),
                value: on,
                onChanged: (v) => ServerPrefs.I.update({'calendar': {'alerts': v}}),
              ),
            ),
            const Heading('Impact'),
            SegmentedButton<String>(
              segments: const [
                ButtonSegment(value: 'high', label: Text('Red folder')),
                ButtonSegment(value: 'medium', label: Text('Red + orange')),
              ],
              selected: {cal['impact'] == 'medium' ? 'medium' : 'high'},
              onSelectionChanged: (s) => ServerPrefs.I.update({'calendar': {'impact': s.first}}),
            ),
            const Heading('Currencies'),
            Wrap(spacing: 8, runSpacing: 4, children: [
              for (final c in currencies)
                FilterChip(
                  label: Text(c),
                  selected: cur.contains(c),
                  onSelected: (v) {
                    final next = [...cur];
                    if (v) {
                      next.add(c);
                    } else if (next.length > 1) {
                      next.remove(c);
                    }
                    ServerPrefs.I.update({'calendar': {'currencies': next}});
                  },
                ),
            ]),
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text('Gold follows USD events, so USD news is tagged as affecting Gold, USD pairs and crypto.',
                  style: TextStyle(color: p.muted, fontSize: 12.5)),
            ),
            const Heading('Warn me before the release'),
            Wrap(spacing: 8, runSpacing: 4, children: [
              for (final e in leads.entries)
                FilterChip(
                  label: Text(e.value),
                  selected: ld.contains(e.key),
                  onSelected: (v) {
                    final next = [...ld];
                    if (v) {
                      next.add(e.key);
                    } else if (next.length > 1) {
                      next.remove(e.key);
                    }
                    ServerPrefs.I.update({'calendar': {'leads': next}});
                  },
                ),
            ]),
            const SizedBox(height: 16),
            Row(children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: () => _call('/api/calendar/refresh', 'Calendar feed refreshed. Open Markets > Calendar.'),
                  icon: const Icon(Icons.refresh),
                  label: const Text('Refresh feed'),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: FilledButton.icon(
                  onPressed: () => _call('/api/calendar/test', 'Test alert sent. A pop-up (and push) should arrive.'),
                  icon: const Icon(Icons.notifications_active_outlined),
                  label: const Text('Test alert'),
                ),
              ),
            ]),
            const SizedBox(height: 8),
            if (msg.isNotEmpty) Panel(child: Text(msg, style: TextStyle(color: ok ? p.gain : p.loss))),
          ]);
        },
      ),
    );
  }
}

// ----------------------------------------------------------------- time zone

const timeZones = [
  ['UTC', 'UTC'],
  ['Europe/London', 'London'],
  ['Europe/Paris', 'Paris, Frankfurt, Madrid'],
  ['Europe/Athens', 'Athens, Helsinki, Kyiv'],
  ['Europe/Istanbul', 'Istanbul'],
  ['Europe/Moscow', 'Moscow'],
  ['Asia/Dubai', 'Dubai, Abu Dhabi'],
  ['Asia/Riyadh', 'Riyadh, Kuwait, Baghdad'],
  ['Asia/Karachi', 'Karachi'],
  ['Asia/Tashkent', 'Tashkent'],
  ['Asia/Almaty', 'Almaty'],
  ['Asia/Kolkata', 'India'],
  ['Asia/Dhaka', 'Dhaka'],
  ['Asia/Bangkok', 'Bangkok, Jakarta'],
  ['Asia/Singapore', 'Singapore, Kuala Lumpur, Manila'],
  ['Asia/Hong_Kong', 'Hong Kong'],
  ['Asia/Shanghai', 'China'],
  ['Asia/Tokyo', 'Tokyo'],
  ['Asia/Seoul', 'Seoul'],
  ['Australia/Sydney', 'Sydney'],
  ['Pacific/Auckland', 'Auckland'],
  ['Africa/Cairo', 'Cairo'],
  ['Africa/Johannesburg', 'Johannesburg'],
  ['Africa/Lagos', 'Lagos'],
  ['Africa/Nairobi', 'Nairobi'],
  ['America/Sao_Paulo', 'Sao Paulo'],
  ['America/Argentina/Buenos_Aires', 'Buenos Aires'],
  ['America/Mexico_City', 'Mexico City'],
  ['America/Bogota', 'Bogota, Lima'],
  ['America/New_York', 'New York (Eastern)'],
  ['America/Chicago', 'Chicago (Central)'],
  ['America/Denver', 'Denver (Mountain)'],
  ['America/Los_Angeles', 'Los Angeles (Pacific)'],
  ['America/Toronto', 'Toronto'],
  ['Pacific/Honolulu', 'Honolulu'],
];

class TimeZonePage extends StatefulWidget {
  const TimeZonePage({super.key});
  @override
  State<TimeZonePage> createState() => _TimeZonePageState();
}

class _TimeZonePageState extends State<TimeZonePage> {
  Map<String, dynamic>? info;
  String? err;

  @override
  void initState() {
    super.initState();
    ServerPrefs.I.load().then((_) => _info());
  }

  Future<void> _info() async {
    if (!Api.ready) return;
    try {
      final d = await Api.get('/api/time') as Map<String, dynamic>;
      if (mounted) setState(() => info = d);
    } catch (e) {
      if (mounted) setState(() => err = '$e');
    }
  }

  Future<void> _pick(String id) async {
    final dev = DateTime.now().timeZoneOffset.inMinutes;
    await ServerPrefs.I.update({
      'general': {'timezone': id, if (id == 'auto') 'tz_offset_min': dev}
    });
    await _info();
  }

  Widget _tile(Pal p, String id, String title, String sub, String current) => ListTile(
        dense: true,
        title: Text(title),
        subtitle: sub.isEmpty ? null : Text(sub, style: TextStyle(color: p.muted, fontSize: 12)),
        trailing: current == id ? Icon(Icons.check_circle, color: p.accent) : null,
        onTap: () => _pick(id),
      );

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    return Scaffold(
      appBar: AppBar(title: const Text('Time zone')),
      body: ListenableBuilder(
        listenable: ServerPrefs.I,
        builder: (context, _) {
          final g = ServerPrefs.I.section('general');
          final current = '${g['timezone'] ?? 'auto'}';
          final i = info;
          final sessions = (i?['sessions'] as List?) ?? [];
          return ListView(padding: const EdgeInsets.all(12), children: [
            if (err != null) Panel(child: Text(err!, style: TextStyle(color: p.loss))),
            if (i != null)
              Panel(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('YOUR TIME', style: TextStyle(color: p.muted, fontSize: 11, letterSpacing: 1)),
                  const SizedBox(height: 4),
                  Text('${i['now']}   ${i['label']}', style: numStyle.copyWith(fontSize: 26, fontWeight: FontWeight.w800)),
                  Text('${i['date']}  -  New York ${i['ny_now']}', style: TextStyle(color: p.muted, fontSize: 12.5)),
                  const SizedBox(height: 10),
                  Text('${(i['forex'] as Map)['text']}', style: TextStyle(color: (i['forex'] as Map)['open'] == true ? p.gain : p.loss, fontSize: 12.5)),
                  const SizedBox(height: 6),
                  Text('Forex and gold hours: ${i['forex_hours']}', style: numStyle.copyWith(fontSize: 12.5)),
                  const SizedBox(height: 8),
                  Text('ICT sessions today (your time)', style: TextStyle(color: p.muted, fontSize: 12)),
                  for (final s in sessions)
                    Text('${(s as Map)['name']}: ${s['start']} - ${s['end']}', style: numStyle.copyWith(fontSize: 12.5)),
                ]),
              ),
            const Heading('Show times in'),
            Panel(
              padding: EdgeInsets.zero,
              child: Column(children: [
                _tile(p, 'auto', 'Automatic', 'Follow this phone (${g['tz_label'] ?? ''})', current),
                const Divider(height: 1),
                for (final z in timeZones) ...[
                  _tile(p, z[0], z[1], z[0], current),
                  const Divider(height: 1),
                ],
              ]),
            ),
            const SizedBox(height: 8),
            Text(
              'Market rules stay in New York time (forex closes Friday 17:00 and reopens Sunday 17:00 there). '
              'This setting only changes how times are shown: alerts, reports, the calendar, session times and market hours. '
              'In automatic mode the app reports its offset each time it opens, so open it after travelling or a clock change.',
              style: TextStyle(color: p.muted, fontSize: 12, height: 1.4),
            ),
          ]);
        },
      ),
    );
  }
}

// ------------------------------------------------------------------- analyst

class AnalystPage extends StatefulWidget {
  const AnalystPage({super.key});
  @override
  State<AnalystPage> createState() => _AnalystPageState();
}

class _AnalystPageState extends State<AnalystPage> {
  @override
  void initState() {
    super.initState();
    ServerPrefs.I.load();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    return Scaffold(
      appBar: AppBar(title: const Text('AI analyst')),
      body: ListenableBuilder(
        listenable: ServerPrefs.I,
        builder: (context, _) {
          final an = ServerPrefs.I.section('analyst');
          final mods = (an['modules'] as Map?)?.cast<String, dynamic>() ?? {};
          final style = '${an['style'] ?? 'intraday'}';
          return ListView(padding: const EdgeInsets.all(12), children: [
            const Heading('Default trading style'),
            SegmentedButton<String>(
              segments: [for (final e in styleLabels.entries) ButtonSegment(value: e.key, label: Text(e.value))],
              selected: {styleLabels.containsKey(style) ? style : 'intraday'},
              onSelectionChanged: (s) => ServerPrefs.I.update({'analyst': {'style': s.first}}),
            ),
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                'Every style reads the full spectrum: MN, 1W, 1D, 4H, 1H, 15m and 5m, and shows BOS, CHoCH, '
                'order blocks and FVGs for each.\nScalp: 1H bias, 15m setup, 5m trigger.\n'
                'Intraday: 4H bias, 1H setup, 15m trigger.\nSwing: weekly bias, daily setup, 4H trigger.\n'
                'The 5m chart refines the entry in every style. Used by the chat, briefings and the Setups tab.',
                style: TextStyle(color: p.muted, fontSize: 12.5, height: 1.45),
              ),
            ),
            const Heading('Safety and tracking'),
            Panel(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Column(children: [
                SwitchListTile(
                  dense: true,
                  title: const Text('News risk scoring'),
                  subtitle: Text('Lowers confidence and warns before red-folder releases',
                      style: TextStyle(color: p.muted, fontSize: 12)),
                  value: an['news_scoring'] != false,
                  onChanged: (v) => ServerPrefs.I.update({'analyst': {'news_scoring': v}}),
                ),
                SwitchListTile(
                  dense: true,
                  title: const Text('Setup journal'),
                  subtitle: Text('Logs every setup and tracks whether TP1 or the stop was hit',
                      style: TextStyle(color: p.muted, fontSize: 12)),
                  value: an['journal'] != false,
                  onChanged: (v) => ServerPrefs.I.update({'analyst': {'journal': v}}),
                ),
              ]),
            ),
            const Heading('Concepts to include'),
            Panel(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Column(children: [
                for (final e in moduleLabels.entries)
                  SwitchListTile(
                    dense: true,
                    title: Text(e.value),
                    value: mods[e.key] != false,
                    onChanged: (v) => ServerPrefs.I.update({'analyst': {'modules': {e.key: v}}}),
                  ),
              ]),
            ),
            Text('Switching a concept off hides it from reports and removes it from the zones used to build setups.',
                style: TextStyle(color: p.muted, fontSize: 12.5, height: 1.4)),
          ]);
        },
      ),
    );
  }
}

// --------------------------------------------------------------- diagnostics

class DiagnosticsPage extends StatefulWidget {
  const DiagnosticsPage({super.key});
  @override
  State<DiagnosticsPage> createState() => _DiagnosticsPageState();
}

class _DiagnosticsPageState extends State<DiagnosticsPage> {
  Map<String, dynamic>? d;
  Map<String, dynamic>? texec;
  String? err;
  String msg = '';
  bool loading = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      loading = true;
      err = null;
    });
    try {
      final r = await Api.get('/api/diagnostics') as Map<String, dynamic>;
      Map<String, dynamic>? t;
      try {
        t = await Api.get('/api/trade/status') as Map<String, dynamic>;
      } catch (_) {
        t = null; // tcexec not reachable - shown below as its own row rather than failing the whole page
      }
      if (mounted) setState(() {
        d = r;
        texec = t;
      });
    } catch (e) {
      if (mounted) setState(() => err = '$e');
    }
    if (mounted) setState(() => loading = false);
  }

  Future<void> _refreshCalendar() async {
    try {
      await Api.post('/api/calendar/refresh');
      msg = 'Calendar refreshed.';
    } catch (e) {
      msg = '$e';
    }
    await _load();
  }

  Widget _kv(Pal p, String k, String v, {Color? color}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(width: 118, child: Text(k, style: TextStyle(color: p.muted, fontSize: 13))),
          Expanded(child: Text(v, style: TextStyle(color: color, fontSize: 13))),
        ]),
      );

  String _ago(num ts) {
    if (ts <= 0) return 'never';
    final m = ((DateTime.now().millisecondsSinceEpoch / 1000 - ts) / 60).round();
    return m < 1 ? 'just now' : (m < 60 ? '$m min ago' : '${m ~/ 60} h ago');
  }

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    final x = d;
    final cal = x?['calendar'] as Map<String, dynamic>?;
    final push = x?['push'] as Map<String, dynamic>?;
    final attempts = (cal?['attempts'] as List?) ?? [];
    final jr = x?['journal'] as Map<String, dynamic>?;
    final tzi = x?['timezone'] as Map<String, dynamic>?;
    final rl = x?['rate_limit'] as Map<String, dynamic>?;
    final sec = x?['security'] as Map<String, dynamic>?;
    final off = sec?['offsite'] as Map<String, dynamic>?;
    final rlLeft = ((rl?['until'] as num?) ?? 0) - DateTime.now().millisecondsSinceEpoch / 1000;
    return Scaffold(
      appBar: AppBar(title: const Text('Diagnostics'), actions: [
        IconButton(onPressed: _load, icon: const Icon(Icons.refresh)),
      ]),
      body: ListView(padding: const EdgeInsets.all(12), children: [
        if (loading) const LinearProgressIndicator(),
        if (err != null) Panel(child: Text(err!, style: TextStyle(color: p.loss))),
        if (x != null) ...[
          const Heading('Server'),
          Panel(
            child: Column(children: [
              if (texec != null) ...[
                _kv(p, 'Trading engine', '${texec!['env']}', color: texec!['env'] == 'live' ? p.warn : p.muted),
                _kv(p, 'Armed', texec!['armed'] == true ? 'Yes' : 'No', color: texec!['armed'] == true ? p.warn : p.muted),
                _kv(p, 'New entries', texec!['halted'] == true ? 'Stopped' : 'Allowed', color: texec!['halted'] == true ? p.loss : p.gain),
              ] else
                _kv(p, 'Trading engine', 'not reachable', color: p.loss),
              _kv(p, 'Live feed', EventService.I.connected ? 'Connected' : 'Offline',
                  color: EventService.I.connected ? p.gain : p.loss),
              _kv(p, 'Events logged', '${(x['events'] as Map)['last_id']}'),
            ]),
          ),
          const Heading('Security and backups'),
          Panel(
            child: Column(children: [
              _kv(p, 'Tailscale',
                  sec?['tailscale_ip'] != null ? '${sec!['tailscale_ip']}:${sec['port']}' : (sec?['tailscale_installed'] == true ? 'Installed, not signed in' : 'Not installed'),
                  color: sec?['tailscale_ip'] != null ? p.gain : p.warn),
              _kv(p, 'API port ${sec?['port'] ?? ''}', sec?['locked'] == true ? 'Locked: only Tailscale can reach it' : 'OPEN to the internet (token only)',
                  color: sec?['locked'] == true ? p.gain : p.warn),
              _kv(p, 'Daily backup', sec?['backup_timer'] == true ? 'Scheduled' : 'Not scheduled', color: sec?['backup_timer'] == true ? p.gain : p.warn),
              _kv(
                  p,
                  'Off-server copy',
                  off?['last_ok'] != null
                      ? '${off!['provider']}: ${_ago(off!['last_ok'] as num)}'
                      : (off?['provider'] != null ? '${off!['provider']}: never sent' : 'Not set up'),
                  color: off?['last_ok'] != null ? p.gain : p.warn),
              if (off?['last_error'] != null) _kv(p, 'Last error', '${off!['last_error']}', color: p.loss),
            ]),
          ),
          const Heading('Push'),
          Panel(
            child: Column(children: [
              _kv(p, 'Status', push?['enabled'] == true ? 'On' : (push?['configured'] == true ? 'Off' : 'No topic set'),
                  color: push?['enabled'] == true ? p.gain : p.warn),
              _kv(p, 'Server', '${push?['server']}'),
              _kv(p, 'Detail', '${push?['detail']}'),
              _kv(p, 'Route', '${push?['route'] ?? 'auto'}'),
              for (final e in ((push?['providers'] as Map?) ?? {}).entries)
                _kv(
                    p,
                    '${e.key}',
                    (e.value['configured'] != true)
                        ? 'not set up'
                        : (((e.value['paused_until'] as num?) ?? 0) > 0
                            ? 'PAUSED (${e.value['error'] ?? ''})'
                            : 'working, sent today ${e.value['sent_today'] ?? 0}'),
                    color: (e.value['configured'] != true) ? p.muted : (((e.value['paused_until'] as num?) ?? 0) > 0 ? p.warn : p.gain)),
            ]),
          ),
          const Heading('Economic calendar'),
          Panel(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              _kv(p, 'Source', '${cal?['source'] ?? 'none yet'}'),
              _kv(p, 'Events stored', '${cal?['count']}'),
              _kv(p, 'Last update', _ago((cal?['updated'] as num?) ?? 0)),
              _kv(p, 'Next retry in', '${cal?['next_try_in']} s'),
              if (cal?['error'] != null) _kv(p, 'Problem', '${cal?['error']}', color: p.loss),
              const SizedBox(height: 6),
              for (final a in attempts)
                Padding(
                  padding: const EdgeInsets.only(top: 3),
                  child: Text(
                    '${(a as Map)['ok'] == true ? 'OK  ' : 'FAIL'}  ${a['source']} (${a['url']}): '
                    '${a['ok'] == true ? '${a['count']} events, ${a['ms']} ms' : a['error']}',
                    style: TextStyle(color: a['ok'] == true ? p.gain : p.loss, fontSize: 12),
                  ),
                ),
            ]),
          ),
          const Heading('Time zone database and rate limits'),
          Panel(
            child: Column(children: [
              _kv(p, 'Time zone data', tzi?['tzdata_ok'] == false ? 'MISSING: built-in US daylight-saving rules are used (pip install tzdata)' : 'OK',
                  color: tzi?['tzdata_ok'] == false ? p.loss : p.gain),
              _kv(p, 'Exchange limits', rlLeft > 0 ? 'Slowing down: ${rl?['why']} (${rlLeft.round()} s)' : 'No limit active',
                  color: rlLeft > 0 ? p.warn : p.gain),
            ]),
          ),
          const Heading('Setup journal'),
          Panel(
            child: Column(children: [
              _kv(p, 'Logged setups', '${jr?['total']}'),
              _kv(p, 'Open now', '${jr?['open']}'),
              _kv(p, 'Last scan', _ago((jr?['last_scan'] as num?) ?? 0)),
              if (jr?['repaint_rate'] != null)
                _kv(p, 'Repainting', '${(jr!['repaint_rate'] as num).toStringAsFixed(0)}% of ${jr['repaint_tracked']} setups vanished before the candle closed'),
              if (jr?['error'] != null) _kv(p, 'Problem', '${jr?['error']}', color: p.loss),
            ]),
          ),
        ],
        const SizedBox(height: 8),
        Row(children: [
          Expanded(child: OutlinedButton(onPressed: _refreshCalendar, child: const Text('Refresh calendar'))),
          const SizedBox(width: 8),
          Expanded(
            child: FilledButton(
              onPressed: () async {
                try {
                  await Api.post('/api/calendar/test');
                  msg = 'Test alert sent.';
                } catch (e) {
                  msg = '$e';
                }
                if (mounted) setState(() {});
              },
              child: const Text('Test alert'),
            ),
          ),
        ]),
        if (msg.isNotEmpty) Panel(child: Text(msg, style: TextStyle(color: p.muted))),
      ]),
    );
  }
}
