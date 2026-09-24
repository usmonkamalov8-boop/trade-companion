// A searchable, live-filtering bottom-sheet symbol picker for Binance USDT-margined futures/spot pairs.
// Backed entirely by the existing GET /api/trade/symbols endpoint (already live, already returns the full,
// real Binance universe, filtered server-side) - no backend changes needed for this. Returns the selected
// symbol (e.g. "BTCUSDT"), or null if dismissed without choosing one.
import 'dart:async';
import 'package:flutter/material.dart';
import 'api.dart';
import 'theme.dart';

Future<String?> showSymbolPicker(BuildContext context, {String kind = 'fut', String? title}) {
  return showModalBottomSheet<String>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    builder: (ctx) => _SymbolPickerSheet(kind: kind, title: title),
  );
}

class _SymbolPickerSheet extends StatefulWidget {
  final String kind;
  final String? title;
  const _SymbolPickerSheet({required this.kind, this.title});
  @override
  State<_SymbolPickerSheet> createState() => _SymbolPickerSheetState();
}

class _SymbolPickerSheetState extends State<_SymbolPickerSheet> {
  final _search = TextEditingController();
  Timer? _debounce;
  List<String> _results = [];
  bool _loading = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _query(''); // preload with the unfiltered top of the list
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _search.dispose();
    super.dispose();
  }

  void _onChanged(String q) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 250), () => _query(q));
  }

  Future<void> _query(String q) async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final r = await Api.get('/api/trade/symbols', {'kind': widget.kind, 'q': q});
      final list = (r as List).cast<String>();
      if (mounted) {
        setState(() {
          _results = list;
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = '$e';
          _loading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
      child: SafeArea(
        child: Container(
          height: MediaQuery.of(context).size.height * 0.75,
          decoration: BoxDecoration(
            color: p.surface,
            borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
            border: Border.all(color: p.outline),
          ),
          child: Column(children: [
            const SizedBox(height: 10),
            Container(width: 40, height: 4, decoration: BoxDecoration(color: p.outline, borderRadius: BorderRadius.circular(2))),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 14, 16, 8),
              child: Row(children: [
                Expanded(
                  child: Text(widget.title ?? 'Select a pair', style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
                ),
                IconButton(icon: const Icon(Icons.close), onPressed: () => Navigator.pop(context)),
              ]),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: TextField(
                controller: _search,
                autofocus: true,
                onChanged: _onChanged,
                style: numStyle,
                decoration: InputDecoration(
                  hintText: 'Search e.g. BTC, ETH, SOL...',
                  prefixIcon: const Icon(Icons.search, size: 20),
                  isDense: true,
                  filled: true,
                  fillColor: p.bg,
                  border: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide(color: p.outline)),
                  focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide(color: p.accent)),
                ),
              ),
            ),
            const SizedBox(height: 8),
            Expanded(
              child: _loading
                  ? const Center(child: CircularProgressIndicator())
                  : _error != null
                      ? Center(
                          child: Padding(
                            padding: const EdgeInsets.all(24),
                            child: Text(_error!, style: TextStyle(color: p.loss), textAlign: TextAlign.center),
                          ),
                        )
                      : _results.isEmpty
                          ? Center(child: Text('No matches', style: TextStyle(color: p.muted)))
                          : ListView.separated(
                              padding: const EdgeInsets.only(bottom: 12),
                              itemCount: _results.length,
                              separatorBuilder: (_, __) => Divider(height: 1, color: p.outline.withOpacity(0.4)),
                              itemBuilder: (ctx, i) {
                                final sym = _results[i];
                                final base = sym.endsWith('USDT') ? sym.substring(0, sym.length - 4) : sym;
                                return ListTile(
                                  dense: true,
                                  leading: CircleAvatar(
                                    radius: 14,
                                    backgroundColor: p.bg,
                                    child: Text(
                                      base.isNotEmpty ? base[0] : '?',
                                      style: TextStyle(fontSize: 12, color: p.accent, fontWeight: FontWeight.bold),
                                    ),
                                  ),
                                  title: Text(sym, style: numStyle.copyWith(fontWeight: FontWeight.w600)),
                                  subtitle: Text(base, style: TextStyle(color: p.muted, fontSize: 12)),
                                  trailing: Icon(Icons.chevron_right, color: p.muted, size: 18),
                                  onTap: () => Navigator.pop(context, sym),
                                );
                              },
                            ),
            ),
          ]),
        ),
      ),
    );
  }
}
