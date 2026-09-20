import 'dart:ui' show FontFeature;
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// One colour palette. Registered as a ThemeExtension, so every widget reads it
/// with `context.pal` and animates smoothly when the palette changes.
class Pal extends ThemeExtension<Pal> {
  final String id;
  final String name;
  final Color bg;
  final Color surface;
  final Color outline;
  final Color accent;
  final Color onAccent;
  final Color gain;
  final Color loss;
  final Color warn;
  final Color muted;
  final Color bubble;
  final Color bubbleBorder;

  const Pal({
    required this.id,
    required this.name,
    required this.bg,
    required this.surface,
    required this.outline,
    required this.accent,
    required this.onAccent,
    required this.gain,
    required this.loss,
    required this.warn,
    required this.muted,
    required this.bubble,
    required this.bubbleBorder,
  });

  @override
  Pal copyWith() => this;

  @override
  Pal lerp(ThemeExtension<Pal>? other, double t) {
    if (other is! Pal) return this;
    Color c(Color a, Color b) => Color.lerp(a, b, t)!;
    return Pal(
      id: t < 0.5 ? id : other.id,
      name: t < 0.5 ? name : other.name,
      bg: c(bg, other.bg),
      surface: c(surface, other.surface),
      outline: c(outline, other.outline),
      accent: c(accent, other.accent),
      onAccent: c(onAccent, other.onAccent),
      gain: c(gain, other.gain),
      loss: c(loss, other.loss),
      warn: c(warn, other.warn),
      muted: c(muted, other.muted),
      bubble: c(bubble, other.bubble),
      bubbleBorder: c(bubbleBorder, other.bubbleBorder),
    );
  }
}

/// Green/red are reserved for gains, losses and bullish/bearish data in every palette.
const palettes = <Pal>[
  Pal(
    id: 'charcoal_gold',
    name: 'Charcoal & Gold',
    bg: Color(0xFF0C1015),
    surface: Color(0xFF141A22),
    outline: Color(0xFF232C37),
    accent: Color(0xFFE0B25B),
    onAccent: Color(0xFF000000),
    gain: Color(0xFF3DBE8B),
    loss: Color(0xFFE5534B),
    warn: Color(0xFFE8A93B),
    muted: Color(0xFF8A99AB),
    bubble: Color(0xFF2A2417),
    bubbleBorder: Color(0xFF4A3C1B),
  ),
  Pal(
    id: 'graphite',
    name: 'Classic Graphite',
    bg: Color(0xFF121212),
    surface: Color(0xFF1C1C1E),
    outline: Color(0xFF303033),
    accent: Color(0xFF8DB4E2),
    onAccent: Color(0xFF000000),
    gain: Color(0xFF4CC38A),
    loss: Color(0xFFEF5B5B),
    warn: Color(0xFFE8A93B),
    muted: Color(0xFF9A9AA0),
    bubble: Color(0xFF22303F),
    bubbleBorder: Color(0xFF34506E),
  ),
  Pal(
    id: 'midnight',
    name: 'Deep Midnight Blue',
    bg: Color(0xFF070B18),
    surface: Color(0xFF0E1530),
    outline: Color(0xFF1F2B57),
    accent: Color(0xFF5B9DFF),
    onAccent: Color(0xFF000000),
    gain: Color(0xFF34D399),
    loss: Color(0xFFF87171),
    warn: Color(0xFFF5B942),
    muted: Color(0xFF8C9BC4),
    bubble: Color(0xFF14285A),
    bubbleBorder: Color(0xFF24408A),
  ),
  Pal(
    id: 'amoled',
    name: 'AMOLED Black',
    bg: Color(0xFF000000),
    surface: Color(0xFF0C0C0C),
    outline: Color(0xFF232323),
    accent: Color(0xFFE9E9EC),
    onAccent: Color(0xFF000000),
    gain: Color(0xFF3DDC97),
    loss: Color(0xFFFF5C5C),
    warn: Color(0xFFF0B04A),
    muted: Color(0xFF8E8E93),
    bubble: Color(0xFF1E1E20),
    bubbleBorder: Color(0xFF38383B),
  ),
];

class ThemeController extends ChangeNotifier {
  ThemeController._();
  static final ThemeController I = ThemeController._();

  String id = 'charcoal_gold';

  Pal get pal => palettes.firstWhere((p) => p.id == id, orElse: () => palettes.first);

  Future<void> load() async {
    final sp = await SharedPreferences.getInstance();
    id = sp.getString('theme') ?? id;
  }

  Future<void> select(String v) async {
    id = v;
    notifyListeners();
    final sp = await SharedPreferences.getInstance();
    await sp.setString('theme', v);
  }
}

extension PalContext on BuildContext {
  Pal get pal => Theme.of(this).extension<Pal>()!;
}

Color biasColor(Pal p, num score) => score >= 15 ? p.gain : (score <= -15 ? p.loss : p.muted);

/// Tabular figures keep columns of prices aligned.
const numStyle = TextStyle(fontFeatures: [FontFeature.tabularFigures()]);

String fnum(dynamic v, [int? d]) {
  if (v == null) return '-';
  final n = (v as num).toDouble();
  final a = n.abs();
  final dec = d ?? (a >= 1000 ? 1 : a >= 100 ? 2 : a >= 10 ? 3 : a >= 1 ? 4 : 5);
  return n.toStringAsFixed(dec);
}

String signed(dynamic v, [int d = 2]) {
  if (v == null) return '-';
  final n = (v as num).toDouble();
  return (n >= 0 ? '+' : '') + n.toStringAsFixed(d);
}

ThemeData buildTheme(Pal p) {
  final scheme = ColorScheme.fromSeed(seedColor: p.accent, brightness: Brightness.dark).copyWith(
    surface: p.bg,
    primary: p.accent,
    onPrimary: p.onAccent,
    secondary: p.accent,
    error: p.loss,
    outline: p.outline,
  );
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: p.bg,
    extensions: <ThemeExtension<dynamic>>[p],
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: p.surface,
      indicatorColor: Color.lerp(p.surface, p.accent, 0.22),
    ),
  );
}

class Panel extends StatelessWidget {
  final Widget child;
  final EdgeInsets padding;
  const Panel({super.key, required this.child, this.padding = const EdgeInsets.all(12)});

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: padding,
      decoration: BoxDecoration(
        color: p.surface,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: p.outline),
      ),
      child: child,
    );
  }
}

class Heading extends StatelessWidget {
  final String text;
  const Heading(this.text, {super.key});
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 14, bottom: 6),
        child: Text(text, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: context.pal.muted)),
      );
}
