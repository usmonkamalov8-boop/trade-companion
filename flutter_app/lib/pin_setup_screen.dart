import 'package:flutter/material.dart';
import 'pin_service.dart';
import 'theme.dart';

/// First-run PIN creation, and also reused after a successful email reset (forgot_pin_screen.dart navigates
/// here once the emailed code checks out).
class PinSetupScreen extends StatefulWidget {
  final VoidCallback onDone;
  const PinSetupScreen({super.key, required this.onDone});
  @override
  State<PinSetupScreen> createState() => _PinSetupScreenState();
}

class _PinSetupScreenState extends State<PinSetupScreen> {
  final _first = TextEditingController();
  final _confirm = TextEditingController();
  bool _confirming = false;
  bool _busy = false;
  String? _error;

  void _submitFirst() {
    if (_first.text.length < 4) {
      setState(() => _error = 'Use at least 4 digits');
      return;
    }
    setState(() {
      _confirming = true;
      _error = null;
    });
  }

  Future<void> _submitConfirm() async {
    if (_confirm.text != _first.text) {
      setState(() {
        _error = "PINs didn't match - try again";
        _confirming = false;
        _first.clear();
        _confirm.clear();
      });
      return;
    }
    setState(() => _busy = true);
    await PinService.I.setPin(_first.text);
    widget.onDone();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    return Scaffold(
      backgroundColor: p.bg,
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(28),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.pin_outlined, size: 56, color: p.muted),
              const SizedBox(height: 16),
              Text(_confirming ? 'Confirm your PIN' : 'Create a PIN',
                  style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              Text(
                _confirming ? 'Enter it once more to confirm.' : "You'll use this to unlock the app - 4 to 8 digits.",
                textAlign: TextAlign.center,
                style: TextStyle(color: p.muted),
              ),
              const SizedBox(height: 20),
              TextField(
                key: ValueKey(_confirming),
                controller: _confirming ? _confirm : _first,
                autofocus: true,
                obscureText: true,
                keyboardType: TextInputType.number,
                maxLength: 8,
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 24, letterSpacing: 8),
                decoration: const InputDecoration(counterText: ''),
                onSubmitted: (_) => _confirming ? _submitConfirm() : _submitFirst(),
              ),
              if (_error != null)
                Padding(padding: const EdgeInsets.only(top: 8), child: Text(_error!, style: TextStyle(color: p.loss))),
              const SizedBox(height: 16),
              FilledButton(
                onPressed: _busy ? null : (_confirming ? _submitConfirm : _submitFirst),
                child: Text(_busy ? 'Saving...' : (_confirming ? 'Confirm' : 'Continue')),
              ),
            ]),
          ),
        ),
      ),
    );
  }
}
