import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'minichart.dart' show fmtPrice;
import 'theme.dart';

/// Position-size calculator: how much to buy or sell so that being stopped out loses a fixed share of the account.
/// Pass [calc] (entry, stop, tp1, side from a setup) to prefill it, or open it empty from Settings.
Future<void> showPositionCalc(BuildContext context, {String? symbol, Map<String, dynamic>? calc}) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (c) => Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.of(c).viewInsets.bottom),
      child: PositionCalc(symbol: symbol, calc: calc),
    ),
  );
}

class PositionCalc extends StatefulWidget {
  final String? symbol;
  final Map<String, dynamic>? calc;
  const PositionCalc({super.key, this.symbol, this.calc});
  @override
  State<PositionCalc> createState() => _PositionCalcState();
}

class _PositionCalcState extends State<PositionCalc> {
  final account = TextEditingController();
  final riskPct = TextEditingController(text: '1');
  final entry = TextEditingController();
  final stop = TextEditingController();
  final tp = TextEditingController();
  final lev = TextEditingController(text: '5');
  final fee = TextEditingController(text: '5');

  @override
  void initState() {
    super.initState();
    final c = widget.calc;
    if (c != null) {
      entry.text = _txt(c['entry']);
      stop.text = _txt(c['stop']);
      tp.text = _txt(c['tp1']);
    }
    _load();
  }

  String _txt(dynamic v) {
    if (v is! num) return '';
    final d = v.toDouble();
    final a = d.abs();
    return d.toStringAsFixed(a >= 1000 ? 1 : (a >= 100 ? 2 : (a >= 1 ? 3 : 5)));
  }

  Future<void> _load() async {
    final sp = await SharedPreferences.getInstance();
    if (!mounted) return;
    setState(() {
      account.text = sp.getString('calc_account') ?? '';
      riskPct.text = sp.getString('calc_risk') ?? '1';
      lev.text = sp.getString('calc_lev') ?? '5';
      fee.text = sp.getString('calc_fee') ?? '5';
    });
  }

  Future<void> _save() async {
    final sp = await SharedPreferences.getInstance();
    await sp.setString('calc_account', account.text);
    await sp.setString('calc_risk', riskPct.text);
    await sp.setString('calc_lev', lev.text);
    await sp.setString('calc_fee', fee.text);
  }

  @override
  void dispose() {
    for (final c in [account, riskPct, entry, stop, tp, lev, fee]) {
      c.dispose();
    }
    super.dispose();
  }

  double? _n(TextEditingController c) => double.tryParse(c.text.trim().replaceAll(',', '.'));

  String _qty(double v) => v >= 100 ? v.toStringAsFixed(1) : (v >= 1 ? v.toStringAsFixed(3) : v.toStringAsFixed(5));
  String _usd(double v) => v.abs() >= 100 ? v.toStringAsFixed(0) : v.toStringAsFixed(2);

  Widget _field(String label, TextEditingController c, {String? hint}) {
    return Expanded(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
        child: TextField(
          controller: c,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          decoration: InputDecoration(labelText: label, hintText: hint, isDense: true, border: const OutlineInputBorder()),
          onChanged: (_) {
            _save();
            setState(() {});
          },
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    final acc = _n(account), rp = _n(riskPct), en = _n(entry), st = _n(stop), t = _n(tp), lv = _n(lev), fe = _n(fee);
    final lines = <String>[];
    final warns = <String>[];
    String head = 'Enter your account size, entry and stop.';
    if (acc != null && rp != null && en != null && st != null && acc > 0 && rp > 0 && en > 0 && st > 0 && en != st) {
      final long = st < en;
      final risk = acc * rp / 100;
      final dist = (en - st).abs();
      final qty = risk / dist;
      final notional = qty * en;
      final stopPct = dist / en * 100;
      final l = (lv == null || lv < 1) ? 1.0 : lv;
      final margin = notional / l;
      final costBp = 2 * ((fe ?? 5) + 2);
      final cost = notional * costBp / 10000;
      head = '${widget.symbol != null ? '${widget.symbol} ' : ''}${long ? 'LONG' : 'SHORT'}: ${_qty(qty)} units';
      lines.add('Risk if stopped out: \$${_usd(risk)} (${rp.toStringAsFixed(rp == rp.roundToDouble() ? 0 : 2)}% of the account)');
      lines.add('Position value: \$${_usd(notional)}   Margin at ${l.toStringAsFixed(l == l.roundToDouble() ? 0 : 1)}x: \$${_usd(margin)}');
      lines.add('Stop is ${stopPct.toStringAsFixed(2)}% away (${fmtPrice(dist)})');
      lines.add('Fees + slippage, round trip (${costBp.toStringAsFixed(0)} bp): about \$${_usd(cost)} = ${(cost / risk).toStringAsFixed(2)}R');
      if (t != null && t > 0 && ((long && t > en) || (!long && t < en))) {
        final rr = (t - en).abs() / dist;
        lines.add('Target ${fmtPrice(t)}: ${rr.toStringAsFixed(2)}R, about \$${_usd(qty * (t - en).abs())} before costs');
      }
      final liq = long ? en * (1 - 1 / l + 0.005) : en * (1 + 1 / l - 0.005);
      lines.add('Rough liquidation price (isolated margin): ${fmtPrice(liq)}');
      if (margin > acc) warns.add('This needs more margin than your account holds. Lower the risk or raise the leverage.');
      if ((long && st <= liq) || (!long && st >= liq)) {
        warns.add('Liquidation would come BEFORE your stop. Lower the leverage.');
      }
      if (stopPct < 0.5) warns.add('A stop this tight means fees cost ${(cost / risk).toStringAsFixed(2)}R before the trade even moves.');
    }
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 20),
      child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Position size', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 8),
        Row(children: [_field('Account (USDT)', account), _field('Risk %', riskPct)]),
        Row(children: [_field('Entry', entry), _field('Stop', stop)]),
        Row(children: [_field('Target (optional)', tp), _field('Leverage', lev), _field('Fee bp', fee)]),
        const SizedBox(height: 12),
        Text(head, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 18)),
        for (final s in lines)
          Padding(padding: const EdgeInsets.only(top: 4), child: Text(s, style: TextStyle(color: p.muted, fontSize: 13))),
        for (final w in warns)
          Padding(padding: const EdgeInsets.only(top: 6), child: Text(w, style: TextStyle(color: p.loss, fontSize: 13, fontWeight: FontWeight.w600))),
        const SizedBox(height: 10),
        Text(
          'Long or short is taken from the stop being below or above the entry. A stop can slip in a fast market, so the real loss can be '
          'larger. Check the exchange for its minimum size, step size and margin rules. This is arithmetic, not advice.',
          style: TextStyle(color: p.muted, fontSize: 11.5, height: 1.4),
        ),
      ]),
    );
  }
}
