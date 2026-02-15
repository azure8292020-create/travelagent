Query Params

originSkyId
*
PARI
String
To get the originSkyId , go to data -> navigation -> relevantFlightParams -> skyId

※ In case the status is 'incomplete'(data->context->status=incomplete), you need to use the /flight/search-incomplete endpoint to get the full data until the status is 'complete'(data->context->status=complete)

destinationSkyId
(optional)
MSYA
String
To get the destinationSkyId , go to data -> navigation -> relevantFlightParams -> skyId

departureDate
(optional)

mm/dd/yyyy
Date (yyyy-mm-dd)
Format: YYYY-MM-dd

returnDate
(optional)

mm/dd/yyyy
Date (yyyy-mm-dd)
Format: YYYY-MM-dd

stops
(optional)
String
It can input multiple values, and the values should be separated by commas
Ex: direct,1stop Default value: Select all

direct : Direct
1stop : 1 stop
2stops : 2+ stops
market
(optional)
String
The Market information can be accessed through the [/get-config] endpoint at data -> market

locale
(optional)
String
The locale information can be accessed through the [/get-config] endpoint at data -> locale

currency
(optional)
String
The currency information can be accessed through the [/get-config] endpoint at data -> currency

adults
(optional)
Number
Adults: 12+ years
Default value: 1

Default: 0
infants
(optional)
Number
Infants: Under 2 years

Default: 0
childrenAge
(optional)
String
Children: 2-12 years

cabinClass
(optional)
String
Cabin class
Default value: economy

economy : Economy
premium_economy : Premium Economy
business : Business
first : First
sort
(optional)
String
best : best
cheapest : price_high
fastest : Fastest
direct : Direct
carriersIds
(optional)
String
Filter flight itinerary data by carrier.
You can retrieve the list of airlines from the response at: data -> filterStats -> carriers -> id