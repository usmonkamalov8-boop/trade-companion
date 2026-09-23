import "dart:convert";
import "package:flutter/material.dart";
import "package:http/http.dart" as http;
import "api.dart";
import "pin_service.dart";
import "pin_setup_screen.dart";
import "theme.dart";

class ForgotPinScreen extends StatefulWidget {
  const ForgotPinScreen({super.key});
  @override
  State<ForgotPinScreen> createState() => _ForgotPinScreenState();
}

class _ForgotPinScreenState extends State<ForgotPinScreen> {
  final _code = TextEditingController();
  bool _sent = false;
  bool _busy = false;
  String? _error;

  Future<void> _requestCode() async {
    setState(() { _busy = true; _error = null; });
    try {
      final r = await http.post(
        Uri.parse("${Api.host}/auth/pin-reset/request"),
        headers: {"Authorization": "Bearer ${Api.token}"},
      );
      setState(() {
        _busy = false;
        if (r.statusCode == 200) { _sent = true; }
        else { _error = jsonDecode(r.body)["detail"]?.toString() ?? "Could not send code"; }
      });
    } catch (e) {
      setState(() { _busy = false; _error = "Network error: $e"; });
    }
  }

  Future<void> _verifyCode() async {
    setState(() { _busy = true; _error = null; });
    try {
      final r = await http.post(
        Uri.parse("${Api.host}/auth/pin-reset/verify"),
        headers: {
          "content-type": "application/json",
          "Authorization": "Bearer ${Api.token}",
        },
        body: jsonEncode({"code": _code.text}),
      );
      if (r.statusCode == 200) {
        await PinService.I.clearPin();
        if (!mounted) return;
        Navigator.of(context).pushReplacement(
          MaterialPageRoute(builder: (_) => PinSetupScreen(onDone: () => Navigator.of(context).pop())),
        );
      } else {
        setState(() { _busy = false; _error = jsonDecode(r.body)["detail"]?.toString() ?? "Incorrect code"; });
      }
    } catch (e) {
      setState(() { _busy = false; _error = "Network error: $e"; });
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    return Scaffold(
      backgroundColor: p.bg,
      appBar: AppBar(title: const Text("Reset PIN")),
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(28),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              if (!_sent) ...[
                const Text("We'll email a 6-digit code to your recovery address.", textAlign: TextAlign.center),
                const SizedBox(height: 16),
                FilledButton(onPressed: _busy ? null : _requestCode, child: Text(_busy ? "Sending..." : "Send code")),
              ] else ...[
                TextField(
                  controller: _code,
                  autofocus: true,
                  keyboardType: TextInputType.number,
                  maxLength: 6,
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontSize: 24, letterSpacing: 8),
                  decoration: const InputDecoration(counterText: "", hintText: "------"),
                ),
                const SizedBox(height: 12),
                FilledButton(onPressed: _busy ? null : _verifyCode, child: Text(_busy ? "Checking..." : "Verify")),
                TextButton(onPressed: _busy ? null : _requestCode, child: const Text("Resend code")),
              ],
              if (_error != null)
                Padding(padding: const EdgeInsets.only(top: 12), child: Text(_error!, style: TextStyle(color: p.loss))),
            ]),
          ),
        ),
      ),
    );
  }
}
