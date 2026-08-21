# Mature-product benchmark matrix

This matrix records architectures worth borrowing.  A benchmark is not an automatic
selection: the exact part must pass load, life, environment, supply, cost and package
reviews before its vendor CAD becomes a controlled interface.

## Product-level adjacent systems for E6

The adjacent market is already dense: seated personal mobility, premium transformable
workstations, consumer following carriers and managed facility robots each prove part
of the WorkCore thesis.  They do **not** prove that WorkCore has equivalent performance,
regulatory status or field maturity, and their existence means that generic claims such
as "a chair with a desk" or "a cart that follows" cannot be treated as novelty.

| Adjacent product/system | Officially evidenced behavior | Pattern worth borrowing | What WorkCore must not infer or claim |
|---|---|---|---|
| [Honda UNI-ONE technology](https://global.honda/en/tech/Hands-free_seated_personal_mobility_device_UNI-ONE/?from=related) / [2025 corporate launch](https://global.honda/en/newsroom/news/2025/c250908aeng.html?from=latest_area) / [design interview](https://global.honda/en/design/interview/202509unione/) | Hands-free seated mobility steered by weight shift; a low position supports boarding/stability and a high position raises eye level. Honda moved from paid trials to corporate sales for use at destinations and designated facility areas, with service contracts. Its exterior deliberately hides wheels and uses a soft, publicly approachable form. | Launch a bounded destination service before promising universal public use; validate with paid design partners; make state height and boarding causal; hide complexity while keeping motion and personal-space intent legible. | WorkCore is not thereby hands-free, omnidirectional, type-certified, publicly deployable or equivalent in stability. Honda also occupies the broad "new seated mobility" territory, so that category alone is not novel. |
| [WHILL Model C2](https://whill.inc/us/whill-model-c2/) | A mature personal mobility product publishes a 51.9–52.8kg mass range, four-step disassembly, 760mm turning radius, 20km nominal range, 50mm obstacle capability and multiple seat/controller adjustments; US material also states FDA Class II status. | Publish configuration-specific mass and mobility limits; design transport as deliberate modules rather than a portability metaphor; provide fit adjustments, manuals, parts and support as part of the product. | WorkCore's stowed-model estimate is about 114.11kg and its pose-invariant base-SKU mass is not yet reconciled; it is not lighter, hand-portable or regulatory-equivalent. A component specification or ergonomic resemblance cannot inherit WHILL's tested range, obstacle, service or medical-device status. |
| [WHILL Autonomous Service](https://whill.inc/ca/mobility-service/how-it-works/autonomous-drive) | Deployment is an operational system: site assessment, mapping, system configuration, live hardware validation, staff training and passenger-flow simulation precede launch; monitoring, maintenance and later map/speed-zone updates continue afterward. | Treat ODD, route versioning, staff training, fleet visibility, rescue and post-launch change control as sellable service work, not installation footnotes. | Buying scanners or writing a route map does not make WorkCore autonomously safe. No public autonomy, staffing level or service readiness can be borrowed from WHILL evidence. |
| [Altwork Signature Station](https://altwork.com/products/altwork-signature-station) / [official FAQ](https://altwork.com/pages/faqs) | A premium workstation synchronizes body support, work surface and monitor through sit, stand and zero-gravity positions. Published information lists about 95kg product mass, pallet delivery, two-person assembly and dedicated service/support expectations. | Coordinate body, display and work-surface transitions; sell a high-value ergonomic experience; plan pallet delivery, installation, cable management, service access and owner education from day one. | A 95kg stationary workstation does not validate mobile stability, ride comfort, health outcomes or context continuity. It also demonstrates why high mass requires an explicit delivery story rather than "luggage" language. |
| [Piaggio Fast Forward gita](https://piaggiofastforward.com/) / [official FAQ](https://piaggiofastforward.com/faqs) | The consumer carrier uses computer vision and a tap to pair/follow rather than GPS; official communication emphasizes pedestrian etiquette and explicitly limits terrain such as sand, snow, mud and tall grass. | Use one-action owner pairing, clear follow/stop status, pedestrian courtesy and honest terrain boundaries; design cargo retention and everyday loading into the journey. | A successful consumer follow carrier does not establish WorkCore's owner recognition, braking, outdoor reliability, portability or safe operation around seated users. "It follows me" and hidden wheels are occupied adjacent ideas, not novelty claims. |
| [Piaggio Fast Forward kilo](https://piaggiofastforward.com/business/kilo) / [launch description](https://piaggiofastforward.com/blog/our-newest-product-launch-pff-kilo) | A facility-focused robot is specified at 66kg with 136kg payload, 8–10h operation, 360-degree 2D lidar plus eight ultrasonic sensors, push-button lead/follow behavior and mounting points for site-specific carts or shelving. It is positioned to join existing workflows with human oversight and without extensive new infrastructure. | Use a controlled B2B wedge; integrate with actual facility loads and routes; make lead/follow/stop behavior obvious; price and test the operator workflow, mounting interfaces and fleet/service layer. | Industrial human-following is not proof of safe personal mobility or public-space autonomy. WorkCore cannot claim equivalent payload, runtime, perception or deployment maturity, and a follow-cart concept by itself is not defensible novelty. |

### E6 cross-benchmark conclusions

- **Borrow the launch method:** Honda, WHILL and kilo all point toward bounded sites,
  operational assessment, staff readiness and continuing service.  This supports E6's
  controlled B2B2C design-partner/rental wedge, not an immediate unrestricted retail launch.
- **Borrow causal transformations:** UNI-ONE changes height for boarding/stability and
  eye-level interaction; Altwork coordinates posture, desk and display.  Every E6 motion
  likewise needs a user benefit, an interlock and a safe recovery path.
- **Tell the truth about mass:** WHILL designs explicit disassembly around roughly half
  E6's current stowed-model estimate; Altwork and kilo use delivery/industrial workflows. E6's pose-invariant base-SKU mass remains an open configuration-control gate. Its "luggage"
  metaphor may describe closed, quiet following behavior only.
- **Make autonomy an operation:** mapping, route change control, training, monitoring,
  maintenance and rescue are product scope.  A purchased perception component is not an
  autonomy or certification claim.
- **Place differentiation narrowly:** the potentially defensible territory is the exact
  four-state combination, fold-invariant low sensing, safe morphing causal chain and
  identity/physical-state/privacy-linked context restoration.  Formal prior-art search,
  claim charting and freedom-to-operate review are required before any novelty statement.

## Component-level mature-product references

| WorkCore function | Mature reference | What to borrow | What not to assume |
|---|---|---|---|
| Locking drawer travel | [Accuride 9300 series](https://www.accuride.com/en-us/products/drawer-slides/heavy-duty-slides/9300-drawer-slide-series) | Three-member full extension, lock-in/lock-out, accessible release lever, silencing bumper; published maximum rating up to 600 lb under specified conditions | Rating in the WorkCore orientation, shock load, pair spacing and mobile duty must be separately derated and tested |
| Lid/display positioning | [Southco E6/ST constant-torque hinge](https://southco.com/en_us_int/hinges/positioning-hinges/e6-st-constant-torque-position-control-hinges) | Factory-set torque, asymmetric lift/lower effort, zero-drift positioning, corrosion-resistant variants; family data states 20,000-cycle torque retention within ±20% | Do not use a friction hinge as the sole safety support for a load-bearing table or canopy |
| Powered lift architecture | [LINAK DL1A lifting column](https://www.linak.com/products/lifting-columns/dl1a) | Integrated guided column, published 1600 N maximum load per leg, controlled ergonomic motion and mature controller ecosystem | Current WorkCore mast package is custom and much narrower; vendor stroke, retracted length, bending moment and IP rating must fit before adoption |
| High-load two-stage lift | [LINAK DL2 lifting column](https://www.linak.com/products/lifting-columns/dl2) | Robust two-stage guide concept for technical workstations | Desk-column duty does not establish outdoor canopy wind resistance |
| Cassette awning drive | [Dometic 9500E 12 V cassette awning](https://media.dometic.com/externalassets/dometic-9500-manual-patio-case-awning-200-_64699.pdf) | Cassette packaging, 12 V tubular drive, limit management and protected stow state; reference manual lists 12 VDC, 3.7 A, 15 rpm, IP44 motor data | WorkCore's 800 x 620 mm canopy has different torque, wind, drainage and pinch risks; use architecture, not copied sizing |
| User posture and reach | [OSHA computer workstation eTool](https://www.osha.gov/etools/computer-workstations/checklists/evaluation) | Neutral shoulders/wrists, adjustable seat/work surface, thigh/leg clearance, waterfall seat edge | Compliance and comfort still require target-population trials |
| Accessible controls | [U.S. Access Board operable parts](https://www.access-board.gov/ada/guides/chapter-3-operable-parts/) | One-hand operation, low dexterity demand, <=5 lbf operating force where applicable, tolerance-aware reach placement | ADA building requirements do not by themselves certify a mobile product |

## Historical E2 adoption direction

These entries are retained for traceability.  E2 canopy and drawer decisions do not
override the E6 product definition, which removes the base canopy and changes storage.

- Use locking slides or an equivalent positive latch on every drawer because the product moves.
- Use constant-torque hinges only for lids/screens; use positive over-centre or pin locks
  for structural tables.
- Package a replaceable lift cartridge with controlled guide pads instead of machining
  the mast slide directly into cosmetic shells.
- Treat the cassette awning as a sealed service module with a drain path, replaceable
  fabric/roller assembly, torque-limited drive and independent stowed confirmation.
- Put frequently used controls inside the verified seated reach envelope and make all
  emergency/stow actions available without navigating the display.

## Historical E2 selected interface candidates

| Function | E2 candidate | Controlled facts used in CAD | Selection boundary |
|---|---|---|---|
| Drawer slide | [Accuride 3832-E10-DO](https://www.accuride.com/media/amasty/amfile/attach/5d3275f703c9dec3898e9331b075578e.pdf) | 250 mm closed length, about 254 mm travel, 12.7 mm nominal side space, 45.7 mm height, 45.5 kg pair rating | Detent open/closed is supplemented by a separate positive transport latch; mobile shock and life remain test gates |
| Drawer latch | [Southco R4-10-30-905-20](https://southco.com/en_us_int/r4-10-30-905-20) | Approximate 77 x 36 x 20 mm interface envelope and two-stage rotary-latch architecture | Final striker, release cable, corrosion and slam-load configuration must be selected with Southco |
| Mast actuator | [LINAK LA20](https://cdn.linak.com/-/media/files/data-sheet-source/en/linear-actuator-la20-data-sheet-eng.pdf) | Ø40 mm-class envelope, 240 mm candidate stroke, 2:1 motion multiplier, up to 2,500 N family rating | Exact built-in length, speed at load, IP option, brake/back-drive behavior and service life must be confirmed in a configured part number |
| Canopy cassette | [Dometic 9500E architecture](https://media.dometic.com/externalassets/dometic-9500-manual-patio-case-awning-200-_64699.pdf) | Cassette, tubular motor, limits, protected stow and replaceable fabric/roller principles | Its 15 rpm reference drive is too slow for E2's sub-8-second emergency target; E2 needs a separately qualified spring-assisted 60 rpm-class system |
