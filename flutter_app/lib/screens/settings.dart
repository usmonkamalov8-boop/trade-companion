import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';
import '../api.dart';
import '../events.dart';
import '../theme.dart';

class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key});
  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  final host = TextEditingController(text: Api.host);
  final token = TextEditingController(text: Api.token);
  bool hide = true;
  String result = '';
  bool ok = false;
  Map<String, dynamic>? push;
  String? pushErr;

  @override
  void initState() {
    super.initState();
    if (Api.ready) _loadPush();
  }

  Future<void> _loadPush() async {
    try {
      final d = await Api.get('/api/push/info') as Map<String, dynamic>;
      if (mounted) {
        setState(() {
          push = d;
          pushErr = null;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          push = null;
          pushErr = 'Push status unavailable: $e';
        });
      }
    }
  }

  Future<void> _save() async {
    await Api.save(host.text, token.text);
    EventService.I.restart(); // reconnect the live feed with the new address/token
    if (mounted) {
      setState(() {
        ok = true;
        result = 'Saved.';
      });
    }
    _loadPush();
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

  Future<void> _testNotification() async {
    try {
      await Api.post('/api/events/test');
      if (mounted) {
        setState(() {
          ok = true;
          result = 'Test event sent. A pop-up should appear within a moment.';
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          ok = false;
          result = 'Could not send the test: $e';
        });
      }
    }
  }

  Future<void> _testPush() async {
    try {
      await Api.post('/api/push/test');
      if (mounted) {
        setState(() {
          ok = true;
          result = 'Test push sent. Close the app and check that the ntfy notification arrives.';
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          ok = false;
          result = '$e';
        });
      }
    }
  }

  Future<void> _copyTopic(String topic) async {
    await Clipboard.setData(ClipboardData(text: topic));
    if (mounted) {
      setState(() {
        ok = true;
        result = 'Topic copied. Paste it into the ntfy app.';
      });
    }
  }

  Future<void> _getNtfy() async {
    await launchUrl(
      Uri.parse('https://play.google.com/store/apps/details?id=io.heckel.ntfy'),
      mode: LaunchMode.externalApplication,
    );
  }

  Widget _pushPanel(Pal p) {
    final info = push;
    final on = info != null && info['enabled'] == true;
    final topic = on ? '${info!['topic']}' : '';
    return Panel(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(Icons.circle, size: 10, color: on ? p.gain : p.warn),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              info == null
                  ? (pushErr ?? 'Checking push status...')
                  : (on ? 'The server sends push notifications' : 'Push is switched off on the server'),
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
          ),
        ]),
        if (on) ...[
          const SizedBox(height: 12),
          Text('Your private topic', style: TextStyle(color: p.muted, fontSize: 12)),
          Row(children: [
            Expanded(child: SelectableText(topic, style: numStyle.copyWith(fontWeight: FontWeight.w600))),
            IconButton(onPressed: () => _copyTopic(topic), icon: const Icon(Icons.copy)),
          ]),
          Text('Server ${info?['server']}   Detail ${info?['detail']}', style: TextStyle(color: p.muted, fontSize: 12)),
        ],
        const SizedBox(height: 12),
        Text(
          '1. Install the free ntfy app.\n'
          '2. In ntfy tap +, paste the topic above and subscribe.\n'
          '3. Allow notifications for ntfy and set its battery use to "No restrictions".\n'
          'Alerts then arrive even when Trade Companion is closed.',
          style: TextStyle(color: p.muted, fontSize: 13, height: 1.45),
        ),
        const SizedBox(height: 12),
        Row(children: [
          Expanded(child: OutlinedButton(onPressed: _getNtfy, child: const Text('Get ntfy app'))),
          const SizedBox(width: 8),
          Expanded(child: FilledButton(onPressed: on ? _testPush : null, child: const Text('Send test push'))),
        ]),
      ]),
    );
  }

  Widget _swatch(Pal x) => Row(mainAxisSize: MainAxisSize.min, children: [
        for (final c in [x.bg, x.surface, x.accent, x.gain, x.loss])
          Container(
            width: 16,
            height: 16,
            margin: const EdgeInsets.only(right: 4),
            decoration: BoxDecoration(
              color: c,
              shape: BoxShape.circle,
              border: Border.all(color: x.outline),
            ),
          ),
      ]);

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    final current = ThemeController.I.id;
    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        const Text('Bot connection', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
        const SizedBox(height: 12),
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
        const SizedBox(height: 8),
        SizedBox(
          width: double.infinity,
          child: TextButton.icon(
            onPressed: _testNotification,
            icon: const Icon(Icons.notifications_active_outlined),
            label: const Text('Send an in-app test notification'),
          ),
        ),
        if (result.isNotEmpty) Panel(child: Text(result, style: TextStyle(color: ok ? p.gain : p.loss))),
        const SizedBox(height: 8),
        Text(
          'The token is stored privately inside this app. Traffic to your VPS is plain HTTP '
          'unless you put HTTPS in front of the server, so keep the token private.',
          style: TextStyle(color: p.muted, fontSize: 12.5, height: 1.4),
        ),
        const SizedBox(height: 24),
        const Text('Background notifications', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
        const SizedBox(height: 10),
        _pushPanel(p),
        const SizedBox(height: 16),
        const Text('Appearance', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
        const SizedBox(height: 10),
        for (final x in palettes)
          GestureDetector(
            onTap: () => ThemeController.I.select(x.id),
            child: Container(
              margin: const EdgeInsets.only(bottom: 8),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: x.surface,
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: current == x.id ? x.accent : x.outline, width: current == x.id ? 2 : 1),
              ),
              child: Row(children: [
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(x.name, style: const TextStyle(fontWeight: FontWeight.w600)),
                    const SizedBox(height: 8),
                    _swatch(x),
                  ]),
                ),
                if (current == x.id) Icon(Icons.check_circle, color: x.accent),
              ]),
            ),
          ),
        const SizedBox(height: 16),
      ]),
    );
  }
}
