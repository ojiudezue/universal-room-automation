**Old  Scheme**

Integration Page
|
—Zone 1 (config button)
	-Zone: Zone 1 (entities, name edit)
-Zone 2 (config button)
	-Zone: Zone 2 (entities, name edit)
-Zone n (config button)
	-Zone: Zone n (entities, name edit)
—Room 1 (config button)
	-Room 1 (entities, name edit)
-Room 2 (config button)
	-Room 2 (entities, name edit)
-Room n (config button)
	Room n (entities, name edit)
|
-Universal Room Automation (config button)
	-Universal room automation (entities, name edit) 
    -Zone: Zone 1 (entities, name edit) <—duplicates
    -Zone: Zone 2 (entities, name edit) <—duplicates
    -Zone: Zone n (entities, name edit) <—duplicates


**Current  Scheme, 3.6.0 c0**

Integration Page
|
—Zone 1 (config button)
	-Zone: Zone 1 (entities, name edit)
-Zone 2 (config button)
	-Zone: Zone 2 (entities, name edit)
-Zone n (config button)
	-Zone: Zone n (entities, name edit)
—Room 1 (config button)
	-Room 1 (entities, name edit)
-Room 2 (config button)
	-Room 2 (entities, name edit)
-Room n (config button)
	Room n (entities, name edit)
|
-Universal Room Automation (config button)
	-Universal room automation (entities, name edit) <—duplicates
    -URA:Coordination Manager (entities, name edit)
    -URA:Zone Manager (entities, name edit)
    -Zone: Back hallway (entities, name edit)
    -Zone: Outside (entities, name edit)


**What I want**

Integration Page
|
-Universal Room Automation (config button) < House configuration
	-Universal room automation (house entities, name edit)
|
-URA:Zone Manager (config button) < Zone configuration, select which Zone to configure
	-Zone: Zone 1 (zone entities, name edit)
	-Zone: Zone 2 (zone entities, name edit)
	-Zone: Zone n (zone entities, name edit)
|
-URA: Coordinator Manager (config button) < Coordinator configuration, select which coordinator  to configure
    -URA:Coordinator 1 (entities, name edit)
    -URA:Coordinator 2 (entities, name edit)
    -URA:Coordinator n (entities, name edit)

—Room 1 (config button)
	-Room 1 (entities, name edit)
-Room 2 (config button)
	-Room 2 (entities, name edit)
-Room n (config button)
	Room n (entities, name edit)


**Possible Acceptable Alternative**

Integration Page
|
-Universal Room Automation (config button) < House configuration
	-Universal room automation (house entities, name edit)
|
-URA:Zone Manager (config button) < Zone configuration, select which Zone to configure
	-Zone: Zone 1 (zone entities, name edit)
	-Zone: Zone 2 (zone entities, name edit)
	-Zone: Zone n (zone entities, name edit)
|
-URA: Coordinator Manager (config button) < Coordinator configuration, select which coordinator  to configure
    -URA:Coordinator 1 (entities, name edit)
    -URA:Coordinator 2 (entities, name edit)
    -URA:Coordinator n (entities, name edit)

|
-URA: Rooms (config button) < Room configuration, select which room  to configure
    -URA:Room 1 (entities, name edit)
    -URA:Room 2 (entities, name edit)
    -URA:Room n (entities, name edit)

