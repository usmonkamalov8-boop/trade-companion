// The app lock: a PIN is the reliable, always-available core (created on first run, recoverable by email via
// forgot_pin_screen.dart if forgotten). Biometric unlock, if enabled in Settings, is offered as a faster
// convenience on top of it - but its failure is never fatal, since the PIN field is always right there.
import 'package:flutter/material.dart';
import 'package:local_auth/local_auth.dart';
import 'forgot_pin_screen.dart';
import 'pin_service.dart';
import 'pin_setup_screen.dart';
import 'prefs.dart';
import 'theme.dart';

// Locks once, at cold start (a fresh launch/full restart), and never re-locks just because the app was
// briefly backgrounded (switching apps, pulling down the notification shade, a phone call) - that repeated
// re-prompting was more aggressive than intended. There is deliberately no app-lifecycle observer here
// anymore: locking is owned entirely by _init()'s one-time check on cold start.
class PinGate extends StatefulWidget {
  final Widget child;
  const PinGate({super.key, required this.child});
  @override
  State<PinGate> createState() => _PinGateState();
}

class _PinGateState extends State<PinGate> {
  final _auth = LocalAuthentication();
  final _pin = TextEditingController();
  bool _checkedSetup = false;
  bool _needsSetup = false;
  bool _locked = true;
  bool _checking = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    final has = await PinService.I.hasPin();
    if (!mounted) return;
    setState(() {
      _needsSetup = !has;
      _checkedSetup = true;
      _locked = has; // no PIN yet -> go straight to setup, not a lock screen with nothing to unlock
    });
    if (has) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _maybeBiometric());
    }
  }

  Future<void> _maybeBiometric() async {
    if (!LocalPrefs.I.biometricLock || !_locked) return;
    var ok = false;
    try {
      ok = await _auth.authenticate(
        localizedReason: 'Unlock Trade Companion',
        biometricOnly: false, // also accepts the device's own PIN/pattern as a fallback within the OS prompt
        persistAcrossBackgrounding: true,
      );
    } catch (_) {
      ok = false; // never surfaced as an error here - the app's own PIN field is the reliable path regardless
    }
    if (mounted && ok) setState(() => _locked = false);
  }

  Future<void> _submitPin() async {
    if (_checking) return;
    setState(() {
      _checking = true;
      _error = null;
    });
    final ok = await PinService.I.verifyPin(_pin.text);
    if (!mounted) return;
    setState(() {
      _checking = false;
      _pin.clear();
      if (ok) {
        _locked = false;
      } else {
        _error = 'Incorrect PIN';
      }
    });
  }

  void _onSetupDone() {
    if (mounted) {
      setState(() {
        _needsSetup = false;
        _locked = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!_checkedSetup) return const SizedBox.shrink();
    if (_needsSetup) return PinSetupScreen(onDone: _onSetupDone);
    if (!_locked) return widget.child;

    final p = context.pal;
    return Scaffold(
      backgroundColor: p.bg,
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(28),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.lock_outline, size: 56, color: p.muted),
              const SizedBox(height: 16),
              const Text('Trade Companion is locked', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
              const SizedBox(height: 20),
              TextField(
                controller: _pin,
                autofocus: true,
                obscureText: true,
                keyboardType: TextInputType.number,
                maxLength: 8,
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 24, letterSpacing: 8),
                decoration: const InputDecoration(counterText: '', hintText: 'PIN'),
                onSubmitted: (_) => _submitPin(),
              ),
              if (_error != null)
                Padding(padding: const EdgeInsets.only(top: 8), child: Text(_error!, style: TextStyle(color: p.loss))),
              const SizedBox(height: 16),
              FilledButton(
                onPressed: _checking ? null : _submitPin,
                child: Text(_checking ? 'Checking...' : 'Unlock'),
              ),
              if (LocalPrefs.I.biometricLock) ...[
                const SizedBox(height: 8),
                TextButton.icon(
                  onPressed: _maybeBiometric,
                  icon: const Icon(Icons.fingerprint),
                  label: const Text('Use fingerprint instead'),
                ),
              ],
              const SizedBox(height: 4),
              TextButton(
                onPressed: () => Navigator.of(context).push(
                  MaterialPageRoute(builder: (_) => const ForgotPinScreen()),
                ),
                child: Text('Forgot PIN?', style: TextStyle(color: p.muted)),
              ),
            ]),
          ),
        ),
      ),
    );
  }
}
