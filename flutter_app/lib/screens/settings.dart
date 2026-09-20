import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';
import '../api.dart';
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
            _tile(context, Icons.auto_graph, 'AI analyst',
                'Default style: ${styleLabels[an['style']] ?? 'Intraday'}', const AnalystPage()),
            _tile(context, Icons.monitor_heart_outlined, 'Diagnostics', 'Server, live feed, push and calendar status',
                const DiagnosticsPage()),
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
      final s = await Api.get('/api/status');
      if (mounted) {
        setState(() {
          ok = true;
          result = 'Connected. Bot service: ${s['service']}. ${s['halted'] == true ? 'Halted.' : 'Running.'}';
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
        Text(
          'The token is stored privately inside this app. Traffic to your VPS is plain HTTP '
          'unless you put HTTPS in front of the server, so keep the token private.',
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
      if (mounted) setState(() => d = r);
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
              _kv(p, 'Bot service', '${x['service']}', color: x['service'] == 'active' ? p.gain : p.warn),
              _kv(p, 'Trading', x['halted'] == true ? 'Halted' : 'Running'),
              _kv(p, 'Live feed', EventService.I.connected ? 'Connected' : 'Offline',
                  color: EventService.I.connected ? p.gain : p.loss),
              _kv(p, 'Events logged', '${(x['events'] as Map)['last_id']}'),
            ]),
          ),
          const Heading('Push'),
          Panel(
            child: Column(children: [
              _kv(p, 'Status', push?['enabled'] == true ? 'On' : (push?['configured'] == true ? 'Off' : 'No topic set'),
                  color: push?['enabled'] == true ? p.gain : p.warn),
              _kv(p, 'Server', '${push?['server']}'),
              _kv(p, 'Detail', '${push?['detail']}'),
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
          const Heading('Setup journal'),
          Panel(
            child: Column(children: [
              _kv(p, 'Logged setups', '${jr?['total']}'),
              _kv(p, 'Open now', '${jr?['open']}'),
              _kv(p, 'Last scan', _ago((jr?['last_scan'] as num?) ?? 0)),
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
