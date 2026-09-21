import 'package:flutter/material.dart';
import '../api.dart';
import '../theme.dart';
import 'settings.dart' show styleLabels;

/// Full multi-timeframe report for one asset with arrows to cycle through the list it came from.
void showAnalysisSheet(BuildContext context, List<Map<String, String>> items, int start, String style, {String focus = ''}) {
  final p = context.pal;
  showModalBottomSheet(
    context: context,
    isScrollControlled: true,
    backgroundColor: p.surface,
    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(16))),
    builder: (_) => FractionallySizedBox(
      heightFactor: 0.92,
      child: DetailSheet(items: items, start: start, style: style, initialFocus: focus),
    ),
  );
}

class DetailSheet extends StatefulWidget {
  final List<Map<String, String>> items;
  final int start;
  final String style, initialFocus;
  const DetailSheet({required this.items, required this.start, required this.style, this.initialFocus = ''});
  @override
  State<DetailSheet> createState() => _DetailSheetState();
}

class _DetailSheetState extends State<DetailSheet> {
  static const focuses = {
    '': 'Full report',
    'xray': 'Trade X-Ray',
    'topdown': 'Top-down (all TFs)',
    'structure': 'BOS / CHoCH',
    'ob': 'Order blocks',
    'fvg': 'Fair value gaps',
    'sd': 'Supply / demand',
    'sr': 'Support / resistance',
    'fib': 'Fibonacci',
    'trend': 'Trendlines',
    'liquidity': 'Liquidity',
    'volume': 'Volume profile',
    'ict': 'ICT',
    'poi': 'POI and setup',
  };
  String focus = '';
  int idx = 0;
  String? text;
  String? err;
  int req = 0;

  @override
  void initState() {
    super.initState();
    focus = widget.initialFocus;
    idx = widget.start.clamp(0, widget.items.length - 1).toInt();
    _load();
  }

  Future<void> _load() async {
    final my = ++req;
    setState(() {
      text = null;
      err = null;
    });
    try {
      final d = await Api.get('/api/analysis', {'name': widget.items[idx]['name']!, 'style': widget.style, if (focus.isNotEmpty) 'focus': focus})
          as Map<String, dynamic>;
      if (mounted && my == req) setState(() => text = '${d['text']}');
    } catch (e) {
      if (mounted && my == req) setState(() => err = '$e');
    }
  }

  void _go(int d) {
    idx = (idx + d).clamp(0, widget.items.length - 1).toInt();
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.pal;
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          IconButton(onPressed: idx > 0 ? () => _go(-1) : null, icon: const Icon(Icons.chevron_left)),
          Expanded(
            child: Text(
              '${widget.items[idx]['name']}  ${widget.items[idx]['label']}  -  ${styleLabels[widget.style] ?? ''}   (${idx + 1}/${widget.items.length})',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15),
            ),
          ),
          IconButton(onPressed: idx < widget.items.length - 1 ? () => _go(1) : null, icon: const Icon(Icons.chevron_right)),
          IconButton(onPressed: () => Navigator.of(context).pop(), icon: const Icon(Icons.close)),
        ]),
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(children: [
            for (final e in focuses.entries)
              Padding(
                padding: const EdgeInsets.only(right: 6),
                child: ChoiceChip(
                  label: Text(e.value),
                  selected: focus == e.key,
                  onSelected: (_) {
                    focus = e.key;
                    _load();
                  },
                ),
              ),
          ]),
        ),
        const SizedBox(height: 8),
        Expanded(
          child: err != null
              ? Text(err!, style: TextStyle(color: p.loss))
              : (text == null
                  ? const Center(child: CircularProgressIndicator())
                  : SingleChildScrollView(
                      child: SelectableText(text!, style: numStyle.copyWith(fontSize: 12.8, height: 1.5)),
                    )),
        ),
      ]),
    );
  }
}
