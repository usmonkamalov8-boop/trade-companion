// Screenshot / screen-recording protection.
//
// Android: WindowManager's FLAG_SECURE genuinely and completely blocks screenshots and screen recording -
// the OS refuses to capture the window at all, including in the recents/app-switcher thumbnail.
//
// iOS has no equivalent API: Apple gives apps no way to block the screenshot gesture. The best achievable,
// and what every serious iOS app in this space does, is: (a) make captured screenshots come out blank via a
// secure-text-field rendering trick, and (b) hide content behind a blur/color overlay in the app switcher
// when the app is backgrounded. That's what this enables - it is not the same guarantee as Android's, and
// no plugin or amount of code can make it one.
import 'package:screen_protector/screen_protector.dart';

class ScreenGuard {
  static bool _on = false;

  static bool get isOn => _on;

  static Future<void> enable() async {
    if (_on) return;
    _on = true;
    try {
      await ScreenProtector.protectDataLeakageOn(); // Android: FLAG_SECURE. No-op on iOS.
      await ScreenProtector.preventScreenshotOn(); // iOS: blanks screenshots. Also fine to call on Android.
    } catch (_) {
      // best-effort: if the platform call fails for any reason, the app still works, just unprotected
    }
  }

  static Future<void> disable() async {
    if (!_on) return;
    _on = false;
    try {
      await ScreenProtector.protectDataLeakageOff();
      await ScreenProtector.preventScreenshotOff();
    } catch (_) {}
  }

  static Future<void> apply(bool enabled) => enabled ? enable() : disable();
}
