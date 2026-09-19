import 'dart:ui' show FontFeature;
import 'package:flutter/material.dart';

/// Palette: near-black slate for the canvas, amber for interactive chrome,
/// and green/red reserved strictly for gains/losses and bullish/bearish data.
class C {
  static const bg = Color(0xFF0C1015);
  static const surface = Color(0xFF141A22);
  static const outline = Color(0xFF232C37);
  static const gold = Color(0xFFE0B25B);
  static const gain = Color(0xFF3DBE8B);
  static const loss = Color(0xFFE5534B);
  static const muted = Color(0xFF8A99AB);
}

Color biasColor(num score) => score >= 15 ? C.gain : (score <= -15 ? C.loss : C.muted);

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

ThemeData buildTheme() {
  final scheme = ColorScheme.fromSeed(seedColor: C.gold, brightness: Brightness.dark)
      .copyWith(surface: C.bg, primary: C.gold, onPrimary: Colors.black);
  return ThemeData(useMaterial3: true, colorScheme: scheme, scaffoldBackgroundColor: C.bg);
}

class Panel extends StatelessWidget {
  final Widget child;
  final EdgeInsets padding;
  const Panel({super.key, required this.child, this.padding = const EdgeInsets.all(12)});

  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: padding,
        decoration: BoxDecoration(
          color: C.surface,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: C.outline),
        ),
        child: child,
      );
}

class Heading extends StatelessWidget {
  final String text;
  const Heading(this.text, {super.key});
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 14, bottom: 6),
        child: Text(text, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: C.muted)),
      );
}
