import 'package:flutter/material.dart';
import '../api.dart';
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

  Future<void> _save() async {
    await Api.save(host.text, token.text);
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
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Bot connection')),
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
          const SizedBox(height: 16),
          if (result.isNotEmpty)
            Panel(child: Text(result, style: TextStyle(color: ok ? C.gain : C.loss))),
          const SizedBox(height: 16),
          const Text(
            'The token is stored privately inside this app. Traffic to your VPS is plain HTTP '
            'unless you put HTTPS in front of the server, so keep the token private.',
            style: TextStyle(color: C.muted, fontSize: 12.5, height: 1.4),
          ),
        ]),
      );
}
