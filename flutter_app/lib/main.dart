import 'package:flutter/material.dart';
import 'api.dart';
import 'auth_gate.dart';
import 'events.dart';
import 'prefs.dart';
import 'screen_guard.dart';
import 'theme.dart';
import 'screens/chart.dart';
import 'screens/chat.dart';
import 'screens/markets.dart';
import 'screens/settings.dart';
import 'screens/trade.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Api.load();
  await ThemeController.I.load();
  await LocalPrefs.I.load();
  await ScreenGuard.apply(LocalPrefs.I.screenProtection);
  EventService.I.restart(); // starts the live event feed (waits until a token is set)
  ServerPrefs.I.load();
  runApp(const App());
}

class App extends StatelessWidget {
  const App({super.key});
  @override
  Widget build(BuildContext context) => ListenableBuilder(
        listenable: ThemeController.I,
        builder: (context, _) => MaterialApp(
          title: 'Trade Companion',
          debugShowCheckedModeBanner: false,
          navigatorKey: Toaster.navKey,
          theme: buildTheme(ThemeController.I.pal),
          home: const AuthGate(child: Shell()),
        ),
      );
}

class Shell extends StatefulWidget {
  const Shell({super.key});
  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  late int i;
  final visited = <int>{};
  final pages = const <Widget>[TradePage(), ChartPage(), ChatPage(), MarketsPage(), SettingsPage()];

  @override
  void initState() {
    super.initState();
    i = Api.ready ? 0 : 4; // no token yet: open Settings first
    visited.add(i);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        body: IndexedStack(index: i, children: [
          for (var k = 0; k < pages.length; k++)
            visited.contains(k) ? pages[k] : const SizedBox.shrink(),
        ]),
        bottomNavigationBar: NavigationBar(
          selectedIndex: i,
          onDestinationSelected: (v) => setState(() {
            i = v;
            visited.add(v);
          }),
          destinations: const [
            NavigationDestination(icon: Icon(Icons.candlestick_chart_outlined), label: 'Trade'),
            NavigationDestination(icon: Icon(Icons.show_chart), label: 'Chart'),
            NavigationDestination(icon: Icon(Icons.forum_outlined), label: 'Assistant'),
            NavigationDestination(icon: Icon(Icons.public), label: 'Markets'),
            NavigationDestination(icon: Icon(Icons.settings_outlined), label: 'Settings'),
          ],
        ),
      );
}
