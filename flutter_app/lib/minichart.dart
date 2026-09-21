import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'api.dart';
import 'prefs.dart';
import 'theme.dart';

String fmtPrice(double v, [int? dec]) {
  if (dec != null) return v.toStringAsFixed(dec);
  final a = v.abs();
  if (a >= 1000) return v.toStringAsFixed(1);
  if (a >= 100) return v.toStringAsFixed(2);
  if (a >= 1) return v.toStringAsFixed(3);
  return v.toStringAsFixed(5);
}

/// Tiny trend line for a list row.
class Sparkline extends StatelessWidget {
  final List<double> values;
  final Color color;
  final double width, height;
  const Sparkline({super.key, required this.values, required this.color, this.width = 84, this.height = 28});

  @override
  Widget build(BuildContext context) => SizedBox(
        width: width,
        height: height,
        child: CustomPaint(painter: _SparkPainter(values, color)),
      );
}

class _SparkPainter extends CustomPainter {
  final List<double> v;
  final Color color;
  _SparkPainter(this.v, this.color);

  @override
  void paint(Canvas canvas, Size size) {
    if (v.length < 2) return;
    final lo = v.reduce(math.min), hi = v.reduce(math.max);
    final span = (hi - lo) == 0 ? 1.0 : (hi - lo);
    Offset pt(int i) => Offset(i / (v.length - 1) * size.width, size.height - 2 - (v[i] - lo) / span * (size.height - 4));
    final path = Path()..moveTo(pt(0).dx, pt(0).dy);
    for (var i = 1; i < v.length; i++) {
      path.lineTo(pt(i).dx, pt(i).dy);
    }
    final fill = Path.from(path)
      ..lineTo(size.width, size.height)
      ..lineTo(0, size.height)
      ..close();
    canvas.drawPath(fill, Paint()..color = color.withAlpha((((0.12)) * 255).round()));
    canvas.drawPath(path, Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.4
      ..strokeJoin = StrokeJoin.round);
    canvas.drawCircle(pt(v.length - 1), 2, Paint()..color = color);
  }

  @override
  bool shouldRepaint(covariant _SparkPainter old) => old.v != v || old.color != color;
}

class ChartData {
  final List<List<double>> candles;
  final List<Map<String, dynamic>> zones, levels, events;
  final String tf;
  final bool closed;
  final int? dec;

  ChartData(this.candles, this.zones, this.levels, this.events, this.tf, this.closed, this.dec);

  static List<Map<String, dynamic>> _maps(dynamic l) =>
      ((l as List?) ?? []).map((e) => (e as Map).cast<String, dynamic>()).toList();

  factory ChartData.fromJson(Map<String, dynamic> j) => ChartData(
        (j['candles'] as List).map((r) => (r as List).map((x) => (x as num).toDouble()).toList()).toList(),
        _maps(j['zones']),
        _maps(j['levels']),
        _maps(j['events']),
        '${j['tf']}',
        j['closed'] == true,
        (j['dec'] as num?)?.toInt(),
      );
}

/// Candlesticks with the analyst's structure drawn on top: order blocks, FVGs, supply/demand, the setup's
/// entry zone, stop and targets, volume-profile levels and BOS / CHoCH markers. Tap or drag for a crosshair.
class CandleChart extends StatefulWidget {
  final ChartData data;
  final double height;
  final ValueChanged<int?>? onCross;
  const CandleChart({super.key, required this.data, this.height = 260, this.onCross});
  @override
  State<CandleChart> createState() => _CandleChartState();
}

class _CandleChartState extends State<CandleChart> {
  int? cross;

  void _set(double dx, double width) {
    final n = widget.data.candles.length;
    final plotW = width - _CandlePainter.axisW;
    if (n == 0 || plotW <= 0) return;
    final i = (dx / plotW * n).floor().clamp(0, n - 1).toInt();
    setState(() => cross = i);
    widget.onCross?.call(i);
  }

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    return LayoutBuilder(builder: (context, box) {
      return GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTapDown: (d) => _set(d.localPosition.dx, box.maxWidth),
        onHorizontalDragUpdate: (d) => _set(d.localPosition.dx, box.maxWidth),
        child: SizedBox(
          height: widget.height,
          width: double.infinity,
          child: CustomPaint(painter: _CandlePainter(widget.data, p, cross)),
        ),
      );
    });
  }
}

class _CandlePainter extends CustomPainter {
  static const axisW = 54.0;
  final ChartData d;
  final Pal p;
  final int? cross;
  _CandlePainter(this.d, this.p, this.cross);

  void _text(Canvas c, String s, Offset o, Color col, {double size = 9, bool right = false}) {
    final tp = TextPainter(
      text: TextSpan(text: s, style: TextStyle(color: col, fontSize: size)),
      textDirection: TextDirection.ltr,
    )..layout();
    tp.paint(c, right ? Offset(o.dx - tp.width, o.dy) : o);
  }

  void _dash(Canvas c, Offset a, Offset b, Paint paint) {
    const dash = 5.0, gap = 4.0;
    final total = (b - a).distance;
    if (total == 0) return;
    final dir = (b - a) / total;
    var pos = 0.0;
    while (pos < total) {
      final end = math.min(pos + dash, total);
      c.drawLine(a + dir * pos, a + dir * end, paint);
      pos += dash + gap;
    }
  }

  Color _zoneColor(Map<String, dynamic> z) {
    final dir = (z['dir'] as num).toInt();
    switch (z['kind']) {
      case 'ENTRY':
        return p.accent;
      case 'FVG':
        return const Color(0xFF9B8AE0);
      case 'OB':
        return dir > 0 ? p.gain : p.loss;
      default:
        return dir > 0 ? p.gain : p.loss;
    }
  }

  @override
  void paint(Canvas canvas, Size size) {
    final n = d.candles.length;
    if (n == 0) return;
    const padT = 8.0, padB = 8.0;
    final plotW = size.width - axisW, plotH = size.height - padT - padB;
    double lo = d.candles.map((c) => c[3]).reduce(math.min);
    double hi = d.candles.map((c) => c[2]).reduce(math.max);
    final span0 = hi - lo == 0 ? 1.0 : hi - lo;
    final xlo = lo - span0 * 0.35, xhi = hi + span0 * 0.35;
    // draw everything that sits near the candles; far-away levels would squash the chart
    final zonesNear = d.zones.where((z) => (z['high'] as num) >= xlo && (z['low'] as num) <= xhi).toList();
    final levelsNear = d.levels.where((l) => (l['price'] as num) >= xlo && (l['price'] as num) <= xhi).toList();
    for (final z in zonesNear) {
      lo = math.min(lo, (z['low'] as num).toDouble());
      hi = math.max(hi, (z['high'] as num).toDouble());
    }
    for (final l in levelsNear) {
      lo = math.min(lo, (l['price'] as num).toDouble());
      hi = math.max(hi, (l['price'] as num).toDouble());
    }
    final span = hi - lo == 0 ? 1.0 : hi - lo;
    double y(double v) => padT + (hi - v) / span * plotH;
    final cw = plotW / n;
    double x(int i) => (i + 0.5) * cw;

    final grid = Paint()
      ..color = p.outline.withAlpha((((0.5)) * 255).round())
      ..strokeWidth = 0.6;
    for (var g = 0; g <= 4; g++) {
      final price = lo + span * g / 4;
      final yy = y(price);
      canvas.drawLine(Offset(0, yy), Offset(plotW, yy), grid);
      _text(canvas, fmtPrice(price, d.dec), Offset(size.width - 2, yy - 5), p.muted, right: true);
    }

    for (final z in zonesNear) {
      final col = _zoneColor(z);
      final x0 = math.min((z['x'] as num).toInt(), n - 1) * cw;
      final top = y((z['high'] as num).toDouble()).clamp(padT, padT + plotH).toDouble();
      final bot = y((z['low'] as num).toDouble()).clamp(padT, padT + plotH).toDouble();
      final rect = Rect.fromLTRB(x0, top, plotW, math.max(bot, top + 1.5));
      final entry = z['kind'] == 'ENTRY';
      canvas.drawRect(rect, Paint()..color = col.withAlpha((((entry ? 0.24 : 0.15)) * 255).round()));
      canvas.drawRect(rect, Paint()
        ..color = col.withAlpha((((entry ? 0.9 : 0.5)) * 255).round())
        ..style = PaintingStyle.stroke
        ..strokeWidth = entry ? 1.2 : 0.7);
      final lab = entry ? 'ENTRY' : '${z['kind']}${z['fresh'] == true ? '' : ' (tested)'}';
      _text(canvas, lab, Offset(x0 + 3, top + 1), col.withAlpha((((0.95)) * 255).round()), size: 8.5);
    }

    for (final l in levelsNear) {
      final price = (l['price'] as num).toDouble();
      final kind = '${l['kind']}';
      final col = kind == 'stop'
          ? p.loss
          : kind == 'tp'
              ? p.gain
              : kind == 'vp'
                  ? p.warn
                  : p.muted;
      _dash(canvas, Offset(0, y(price)), Offset(plotW, y(price)), Paint()
        ..color = col
        ..strokeWidth = kind == 'vp2' ? 0.8 : 1.2);
      _text(canvas, '${l['label']}', Offset(plotW - 3, y(price) - 10), col, right: true, size: 8.5);
    }

    for (var i = 0; i < n; i++) {
      final c = d.candles[i];
      final up = c[4] >= c[1];
      final col = up ? p.gain : p.loss;
      final wick = Paint()
        ..color = col
        ..strokeWidth = 1;
      canvas.drawLine(Offset(x(i), y(c[2])), Offset(x(i), y(c[3])), wick);
      final top = y(math.max(c[1], c[4])), bot = y(math.min(c[1], c[4]));
      final w = math.max(1.0, cw * 0.68);
      canvas.drawRect(Rect.fromLTWH(x(i) - w / 2, top, w, math.max(1.0, bot - top)), Paint()..color = col);
    }

    for (final e in d.events) {
      final i = (e['x'] as num).toInt();
      if (i < 0 || i >= n) continue;
      final dir = (e['dir'] as num).toInt();
      final col = dir > 0 ? p.gain : p.loss;
      final yy = y((e['level'] as num).toDouble());
      if (yy < padT || yy > padT + plotH) continue;
      _dash(canvas, Offset(x(i), yy), Offset(math.min(plotW, x(i) + cw * 10), yy), Paint()
        ..color = col.withAlpha((((0.7)) * 255).round())
        ..strokeWidth = 0.8);
      _text(canvas, '${e['type']}${dir > 0 ? ' \u2191' : ' \u2193'}', Offset(x(i), yy - 10), col, size: 8.5);
    }

    if (cross != null && cross! < n) {
      final c = d.candles[cross!];
      final cp = Paint()
        ..color = p.muted.withAlpha((((0.8)) * 255).round())
        ..strokeWidth = 0.7;
      canvas.drawLine(Offset(x(cross!), padT), Offset(x(cross!), padT + plotH), cp);
      canvas.drawLine(Offset(0, y(c[4])), Offset(plotW, y(c[4])), cp);
      final tag = fmtPrice(c[4], d.dec);
      _text(canvas, tag, Offset(size.width - 2, y(c[4]) - 5), p.accent, right: true, size: 9.5);
    }
  }

  @override
  bool shouldRepaint(covariant _CandlePainter old) => old.d != d || old.cross != cross || old.p != p;
}

/// Loads /api/chart and shows the chart with timeframe and length chips. Used inside the screener rows.
class MiniChartPanel extends StatefulWidget {
  final String name, style;
  final String initialTf;
  final VoidCallback? onReport, onXray;
  const MiniChartPanel({super.key, required this.name, required this.style, this.initialTf = '1h', this.onReport, this.onXray});
  @override
  State<MiniChartPanel> createState() => _MiniChartPanelState();
}

class _MiniChartPanelState extends State<MiniChartPanel> {
  static const tfs = {'5m': '5m', '15m': '15m', '1h': '1H', '4h': '4H', '1d': '1D', '1w': '1W'};
  String tf = '1h';
  int n = 100;
  ChartData? data;
  String? err;
  bool loading = false;
  int? cross;
  int req = 0;

  @override
  void initState() {
    super.initState();
    tf = tfs.containsKey(widget.initialTf) ? widget.initialTf : '1h';
    _load();
  }

  Future<void> _load() async {
    final my = ++req;
    setState(() {
      loading = true;
      err = null;
      cross = null;
    });
    try {
      final j = await Api.get('/api/chart', {'name': widget.name, 'tf': tf, 'n': '$n', 'style': widget.style}) as Map<String, dynamic>;
      if (mounted && my == req) setState(() => data = ChartData.fromJson(j));
    } catch (e) {
      if (mounted && my == req) setState(() => err = '$e');
    }
    if (mounted && my == req) setState(() => loading = false);
  }

  String _readout(ChartData d) {
    final i = (cross ?? d.candles.length - 1).clamp(0, d.candles.length - 1).toInt();
    final c = d.candles[i];
    final t = TzClock.dt(c[0]);
    final when = '${TzClock.two(t.day)}/${TzClock.two(t.month)} ${TzClock.two(t.hour)}:${TzClock.two(t.minute)}';
    String f(double v) => fmtPrice(v, d.dec);
    return '$when   O ${f(c[1])}  H ${f(c[2])}  L ${f(c[3])}  C ${f(c[4])}';
  }

  Widget _legend(Pal p) {
    Widget dot(Color c, String t) => Padding(
          padding: const EdgeInsets.only(right: 10),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Container(width: 9, height: 9, decoration: BoxDecoration(color: c.withAlpha((((0.6)) * 255).round()), borderRadius: BorderRadius.circular(2))),
            const SizedBox(width: 4),
            Text(t, style: TextStyle(color: p.muted, fontSize: 10.5)),
          ]),
        );
    return Wrap(children: [
      dot(p.gain, 'Bull OB / demand'),
      dot(p.loss, 'Bear OB / supply'),
      dot(const Color(0xFF9B8AE0), 'FVG'),
      dot(p.accent, 'Entry zone'),
      dot(p.warn, 'POC'),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    final d = data;
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(children: [
            for (final e in tfs.entries)
              Padding(
                padding: const EdgeInsets.only(right: 6),
                child: ChoiceChip(
                  label: Text(e.value),
                  visualDensity: VisualDensity.compact,
                  selected: tf == e.key,
                  onSelected: (_) {
                    tf = e.key;
                    _load();
                  },
                ),
              ),
            const SizedBox(width: 8),
            for (final k in [50, 100, 150])
              Padding(
                padding: const EdgeInsets.only(right: 6),
                child: ChoiceChip(
                  label: Text('$k'),
                  visualDensity: VisualDensity.compact,
                  selected: n == k,
                  onSelected: (_) {
                    n = k;
                    _load();
                  },
                ),
              ),
          ]),
        ),
        if (loading) const Padding(padding: EdgeInsets.only(top: 6), child: LinearProgressIndicator()),
        if (err != null) Padding(padding: const EdgeInsets.only(top: 6), child: Text(err!, style: TextStyle(color: p.loss, fontSize: 12))),
        if (d != null) ...[
          const SizedBox(height: 6),
          Text(_readout(d), style: numStyle.copyWith(fontSize: 11.5, color: p.muted)),
          if (d.closed)
            Text('Market closed (weekend): the chart shows the last session, no signals.', style: TextStyle(color: p.loss, fontSize: 11.5)),
          const SizedBox(height: 4),
          CandleChart(data: d, onCross: (i) => setState(() => cross = i)),
          const SizedBox(height: 6),
          _legend(p),
        ],
        const SizedBox(height: 4),
        Row(children: [
          TextButton.icon(onPressed: widget.onReport, icon: const Icon(Icons.article_outlined, size: 18), label: const Text('Full report')),
          TextButton.icon(onPressed: widget.onXray, icon: const Icon(Icons.troubleshoot, size: 18), label: const Text('Trade X-Ray')),
        ]),
      ]),
    );
  }
}
