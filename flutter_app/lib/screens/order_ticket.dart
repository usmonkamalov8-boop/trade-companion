// Manual order ticket (futures) and spot-grid wizard, as two tabs.
import 'package:flutter/material.dart';
import '../api.dart';
import '../symbol_picker.dart';
import '../theme.dart';

class OrderTicketPage extends StatefulWidget {
  final int startTab;
  const OrderTicketPage({super.key, this.startTab = 0});
  @override
  State<OrderTicketPage> createState() => _OrderTicketPageState();
}

class _OrderTicketPageState extends State<OrderTicketPage> with SingleTickerProviderStateMixin {
  late TabController tab;
  @override
  void initState() {
    super.initState();
    tab = TabController(length: 2, vsync: this, initialIndex: widget.startTab);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: const Text('New order'),
          bottom: TabBar(controller: tab, tabs: const [Tab(text: 'Futures'), Tab(text: 'Spot grid')]),
        ),
        body: TabBarView(controller: tab, children: const [_FuturesTicket(), _GridWizard()]),
      );
}

/// A tappable, non-freeform symbol selector - opens the searchable picker rather than accepting typed text
/// directly, so every symbol placed here is guaranteed to be a real, live Binance pair rather than a typo.
class _SymbolField extends StatelessWidget {
  final String symbol;
  final String kind; // 'fut' | 'spot' - which market the picker searches
  final String title;
  final ValueChanged<String> onChanged;
  const _SymbolField({required this.symbol, required this.kind, required this.title, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    return InkWell(
      borderRadius: BorderRadius.circular(12),
      onTap: () async {
        final s = await showSymbolPicker(context, kind: kind, title: title);
        if (s != null) onChanged(s);
      },
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
        decoration: BoxDecoration(
          color: p.surface,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: p.outline),
        ),
        child: Row(children: [
          CircleAvatar(
            radius: 15,
            backgroundColor: p.bg,
            child: Text(
              symbol.isNotEmpty ? symbol[0] : '?',
              style: TextStyle(fontSize: 13, color: p.accent, fontWeight: FontWeight.bold),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(symbol.isEmpty ? 'Select a pair' : symbol,
                  style: numStyle.copyWith(fontSize: 17, fontWeight: FontWeight.w700)),
              Text(kind == 'fut' ? 'USDT-M Futures' : 'Spot', style: TextStyle(color: p.muted, fontSize: 12)),
            ]),
          ),
          Icon(Icons.unfold_more, color: p.muted),
        ]),
      ),
    );
  }
}

/// A labeled group of fields, giving the ticket real visual sections instead of one long flat list.
class _Section extends StatelessWidget {
  final String label;
  final Widget child;
  const _Section({required this.label, required this.child});

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Panel(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label.toUpperCase(), style: TextStyle(color: p.muted, fontSize: 11, fontWeight: FontWeight.w700, letterSpacing: 0.6)),
          const SizedBox(height: 10),
          child,
        ]),
      ),
    );
  }
}

class _FuturesTicket extends StatefulWidget {
  const _FuturesTicket();
  @override
  State<_FuturesTicket> createState() => _FuturesTicketState();
}

class _FuturesTicketState extends State<_FuturesTicket> {
  final symbol = TextEditingController(text: 'BTCUSDT');
  final price = TextEditingController();
  final stop = TextEditingController();
  final tp = TextEditingController();
  final qty = TextEditingController();
  final notional = TextEditingController();
  final riskPct = TextEditingController(text: '0.5');
  final leverage = TextEditingController(text: '3');
  String side = 'LONG';
  String entryType = 'LIMIT';
  String marginType = 'ISOLATED';
  String sizeMode = 'risk'; // risk | qty | notional
  Map<String, dynamic>? preview;
  String? error;
  bool busy = false;

  Map<String, dynamic> _ticket() {
    final t = <String, dynamic>{'symbol': symbol.text.trim().toUpperCase(), 'side': side, 'entry_type': entryType, 'margin_type': marginType, 'leverage': int.tryParse(leverage.text) ?? 3};
    if (entryType == 'LIMIT' && price.text.isNotEmpty) t['price'] = double.tryParse(price.text);
    if (stop.text.isNotEmpty) t['stop'] = double.tryParse(stop.text);
    if (tp.text.isNotEmpty) t['tp'] = double.tryParse(tp.text);
    if (sizeMode == 'qty' && qty.text.isNotEmpty) t['qty'] = double.tryParse(qty.text);
    if (sizeMode == 'notional' && notional.text.isNotEmpty) t['notional'] = double.tryParse(notional.text);
    if (sizeMode == 'risk' && riskPct.text.isNotEmpty) t['risk_pct'] = double.tryParse(riskPct.text);
    return t;
  }

  Future<void> _preview() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final r = await Api.post('/api/trade/order/preview', _ticket());
      setState(() => preview = r);
    } catch (e) {
      setState(() => error = '$e');
    } finally {
      setState(() => busy = false);
    }
  }

  Future<void> _submit() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('$side ${symbol.text.toUpperCase()}'),
        content: Text('Size ${preview?['qty']}, value ${(preview?['notional'] as num?)?.toStringAsFixed(0)} USDT, ${leverage.text}x $marginType.\nStop ${stop.text.isEmpty ? '-' : stop.text}   Target ${tp.text.isEmpty ? '-' : tp.text}'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Place order')),
        ],
      ),
    );
    if (ok != true) return;
    setState(() => busy = true);
    try {
      final r = await Api.post('/api/trade/order', _ticket());
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(r['ok'] == true ? 'Order placed' : '${r['error']}')));
        if (r['ok'] == true) Navigator.pop(context);
      }
    } catch (e) {
      setState(() => error = '$e');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    final v = preview;
    final ok = v?['ok'] == true;
    final isLong = side == 'LONG';
    return ListView(padding: const EdgeInsets.all(12), children: [
      _SymbolField(
        symbol: symbol.text.trim().toUpperCase(),
        kind: 'fut',
        title: 'Select futures pair',
        onChanged: (s) => setState(() => symbol.text = s),
      ),
      const SizedBox(height: 14),
      Row(children: [
        Expanded(
          child: _SideButton(label: 'Long', selected: isLong, color: p.gain, onTap: () => setState(() => side = 'LONG')),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: _SideButton(label: 'Short', selected: !isLong, color: p.loss, onTap: () => setState(() => side = 'SHORT')),
        ),
      ]),
      const SizedBox(height: 14),
      _Section(
        label: 'Entry',
        child: Column(children: [
          SegmentedButton<String>(
            segments: const [ButtonSegment(value: 'LIMIT', label: Text('Limit')), ButtonSegment(value: 'MARKET', label: Text('Market'))],
            selected: {entryType},
            onSelectionChanged: (v) => setState(() => entryType = v.first),
          ),
          if (entryType == 'LIMIT') ...[
            const SizedBox(height: 10),
            TextField(controller: price, keyboardType: const TextInputType.numberWithOptions(decimal: true), decoration: const InputDecoration(labelText: 'Limit price')),
          ],
        ]),
      ),
      _Section(
        label: 'Protection',
        child: Row(children: [
          Expanded(child: TextField(controller: stop, keyboardType: const TextInputType.numberWithOptions(decimal: true), decoration: const InputDecoration(labelText: 'Stop'))),
          const SizedBox(width: 8),
          Expanded(child: TextField(controller: tp, keyboardType: const TextInputType.numberWithOptions(decimal: true), decoration: const InputDecoration(labelText: 'Target'))),
        ]),
      ),
      _Section(
        label: 'Position size',
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SegmentedButton<String>(
            segments: const [ButtonSegment(value: 'risk', label: Text('Risk %')), ButtonSegment(value: 'qty', label: Text('Quantity')), ButtonSegment(value: 'notional', label: Text('Value'))],
            selected: {sizeMode},
            onSelectionChanged: (v) => setState(() => sizeMode = v.first),
          ),
          const SizedBox(height: 10),
          if (sizeMode == 'risk') TextField(controller: riskPct, keyboardType: const TextInputType.numberWithOptions(decimal: true), decoration: const InputDecoration(labelText: 'Risk % of account', suffixText: '%')),
          if (sizeMode == 'qty') TextField(controller: qty, keyboardType: const TextInputType.numberWithOptions(decimal: true), decoration: const InputDecoration(labelText: 'Quantity')),
          if (sizeMode == 'notional') TextField(controller: notional, keyboardType: const TextInputType.numberWithOptions(decimal: true), decoration: const InputDecoration(labelText: 'Position value (USDT)')),
          const SizedBox(height: 10),
          Row(children: [
            Expanded(
              child: TextField(controller: leverage, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Leverage')),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: DropdownButtonFormField<String>(
                initialValue: marginType,
                items: const [DropdownMenuItem(value: 'ISOLATED', child: Text('Isolated')), DropdownMenuItem(value: 'CROSSED', child: Text('Cross'))],
                onChanged: (v) => setState(() => marginType = v!),
                decoration: const InputDecoration(labelText: 'Margin'),
              ),
            ),
          ]),
        ]),
      ),
      FilledButton.tonal(onPressed: busy ? null : _preview, child: const Text('Preview')),
      const SizedBox(height: 8),
      if (error != null) Text(error!, style: TextStyle(color: p.loss)),
      if (v != null)
        Panel(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (ok) ...[
              Text('Size ${v['qty']}   value ${(v['notional'] as num).toStringAsFixed(0)} USDT', style: numStyle),
              Text('Risk if stopped: ${(v['risk_amount'] as num? ?? 0).toStringAsFixed(2)} USDT (${(v['risk_pct'] as num? ?? 0).toStringAsFixed(2)}% of account)'),
              if (v['rr'] != null) Text('Reward:risk ${(v['rr'] as num).toStringAsFixed(2)}'),
              if (v['liq_est'] != null) Text('Estimated liquidation ${v['liq_est']}', style: TextStyle(color: p.warn)),
            ] else
              for (final r in (v['violations'] as List? ?? [])) Text('$r', style: TextStyle(color: p.loss)),
            for (final w in (v['warnings'] as List? ?? [])) Text(w, style: TextStyle(color: p.warn)),
          ]),
        ),
      const SizedBox(height: 12),
      if (ok)
        SizedBox(
          height: 50,
          child: FilledButton(
            style: FilledButton.styleFrom(backgroundColor: isLong ? p.gain : p.loss, foregroundColor: Colors.white, textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
            onPressed: busy ? null : _submit,
            child: Text('${isLong ? 'Buy / Long' : 'Sell / Short'} ${symbol.text.toUpperCase()}'),
          ),
        ),
    ]);
  }
}

class _SideButton extends StatelessWidget {
  final String label;
  final bool selected;
  final Color color;
  final VoidCallback onTap;
  const _SideButton({required this.label, required this.selected, required this.color, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    return InkWell(
      borderRadius: BorderRadius.circular(12),
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 150),
        padding: const EdgeInsets.symmetric(vertical: 14),
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: selected ? color.withAlpha(46) : p.surface,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: selected ? color : p.outline, width: selected ? 1.6 : 1),
        ),
        child: Text(label, style: TextStyle(color: selected ? color : p.muted, fontWeight: FontWeight.w700, fontSize: 15)),
      ),
    );
  }
}

class _GridWizard extends StatefulWidget {
  const _GridWizard();
  @override
  State<_GridWizard> createState() => _GridWizardState();
}

class _GridWizardState extends State<_GridWizard> {
  final symbol = TextEditingController(text: 'BTCUSDT');
  final lower = TextEditingController();
  final upper = TextEditingController();
  final gridsC = TextEditingController(text: '20');
  final invest = TextEditingController();
  String mode = 'arithmetic';
  Map<String, dynamic>? plan;
  String? error;
  bool busy = false;

  Map<String, dynamic> _cfg() => {
        'symbol': symbol.text.trim().toUpperCase(),
        'lower': double.tryParse(lower.text) ?? 0,
        'upper': double.tryParse(upper.text) ?? 0,
        'grids': int.tryParse(gridsC.text) ?? 0,
        'invest': double.tryParse(invest.text) ?? 0,
        'mode': mode,
      };

  Future<void> _plan() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final r = await Api.post('/api/trade/grid/plan', _cfg());
      setState(() => plan = r);
    } catch (e) {
      setState(() => error = '$e');
    } finally {
      setState(() => busy = false);
    }
  }

  Future<void> _applySuggestion() async {
    final sg = plan?['suggest'] as Map<String, dynamic>?;
    if (sg == null) return;
    setState(() {
      lower.text = (sg['lower'] as num).toStringAsFixed(4);
      upper.text = (sg['upper'] as num).toStringAsFixed(4);
      gridsC.text = '${sg['suggested_grids']}';
    });
    await _plan();
  }

  Future<void> _start() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Start grid ${symbol.text.toUpperCase()}'),
        content: Text('${plan?['n']} grids between ${lower.text} and ${upper.text}, investing ${invest.text} USDT.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Start')),
        ],
      ),
    );
    if (ok != true) return;
    setState(() => busy = true);
    try {
      final r = await Api.post('/api/trade/grid/start', _cfg());
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(r['ok'] == true ? 'Grid started' : '${r['error']}')));
        if (r['ok'] == true) Navigator.pop(context);
      }
    } catch (e) {
      setState(() => error = '$e');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    final v = plan;
    final ok = v?['ok'] == true;
    final sg = v?['suggest'] as Map<String, dynamic>?;
    return ListView(padding: const EdgeInsets.all(12), children: [
      _SymbolField(
        symbol: symbol.text.trim().toUpperCase(),
        kind: 'spot',
        title: 'Select spot pair',
        onChanged: (s) => setState(() => symbol.text = s),
      ),
      const SizedBox(height: 14),
      _Section(
        label: 'Range',
        child: Column(children: [
          Row(children: [
            Expanded(child: TextField(controller: lower, keyboardType: const TextInputType.numberWithOptions(decimal: true), decoration: const InputDecoration(labelText: 'Lower price'))),
            const SizedBox(width: 8),
            Expanded(child: TextField(controller: upper, keyboardType: const TextInputType.numberWithOptions(decimal: true), decoration: const InputDecoration(labelText: 'Upper price'))),
          ]),
          const SizedBox(height: 10),
          SegmentedButton<String>(
            segments: const [ButtonSegment(value: 'arithmetic', label: Text('Even spacing')), ButtonSegment(value: 'geometric', label: Text('% spacing'))],
            selected: {mode},
            onSelectionChanged: (v) => setState(() => mode = v.first),
          ),
        ]),
      ),
      _Section(
        label: 'Grid setup',
        child: Row(children: [
          Expanded(child: TextField(controller: gridsC, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Number of grids'))),
          const SizedBox(width: 8),
          Expanded(child: TextField(controller: invest, keyboardType: const TextInputType.numberWithOptions(decimal: true), decoration: const InputDecoration(labelText: 'Investment (USDT)'))),
        ]),
      ),
      FilledButton.tonal(onPressed: busy ? null : _plan, child: const Text('Calculate')),
      const SizedBox(height: 8),
      if (error != null) Text(error!, style: TextStyle(color: p.loss)),
      if (sg != null)
        Panel(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Suggestion from recent price history:', style: TextStyle(color: p.muted, fontSize: 12)),
            Text('${(sg['lower'] as num).toStringAsFixed(4)} - ${(sg['upper'] as num).toStringAsFixed(4)}  (${(sg['range_pct'] as num).toStringAsFixed(1)}% wide), ~${sg['suggested_grids']} grids', style: numStyle),
            TextButton(onPressed: _applySuggestion, child: const Text('Use this')),
          ]),
        ),
      if (v != null)
        Panel(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (ok) ...[
              Text('Order size ${v['qty']} per sell, ${v['buy_orders']} buy / ${v['sell_orders']} sell orders', style: numStyle),
              Text('Net per cycle ~${(v['net_per_cycle_avg_pct'] as num).toStringAsFixed(2)}% after fees'),
              Text('If price falls to the lower edge: ${(v['pnl_if_price_at_lower'] as num).toStringAsFixed(2)} USDT', style: TextStyle(color: p.loss)),
              Text('If price rises to the upper edge: ${(v['pnl_if_price_at_upper'] as num).toStringAsFixed(2)} USDT', style: TextStyle(color: p.gain)),
              if (v['simulation'] != null)
                for (final e in (v['simulation'] as Map).entries)
                  if (e.value is Map && (e.value as Map)['cycles'] != null)
                    Text('${e.key} replay: ${(e.value as Map)['cycles']} cycles, return ${((e.value as Map)['total_return_pct'] as num).toStringAsFixed(1)}% (buy & hold ${((e.value as Map)['hold_return_pct'] as num).toStringAsFixed(1)}%)', style: TextStyle(color: p.muted, fontSize: 12)),
            ] else
              for (final e in (v['errors'] as List? ?? [])) Text('$e', style: TextStyle(color: p.loss)),
            for (final w in (v['warnings'] as List? ?? [])) Text('$w', style: TextStyle(color: p.warn)),
          ]),
        ),
      const SizedBox(height: 12),
      if (ok)
        SizedBox(
          height: 50,
          child: FilledButton(
            style: FilledButton.styleFrom(textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
            onPressed: busy ? null : _start,
            child: Text('Start grid ${symbol.text.toUpperCase()}'),
          ),
        ),
    ]);
  }
}
