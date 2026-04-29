import 'package:flutter_test/flutter_test.dart';

import 'package:neo_vision_mobile/main.dart';

void main() {
  testWidgets('App carrega título NeoVision', (WidgetTester tester) async {
    await tester.pumpWidget(const NeoVisionApp());
    expect(find.text('NeoVision AI'), findsWidgets);
  });
}
