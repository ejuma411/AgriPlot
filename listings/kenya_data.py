# kenya_data.py

KENYA_COUNTIES = [
    'Baringo', 'Bomet', 'Bungoma', 'Busia', 'Elgeyo Marakwet', 'Embu', 'Garissa',
    'Homa Bay', 'Isiolo', 'Kajiado', 'Kakamega', 'Kericho', 'Kiambu', 'Kilifi',
    'Kirinyaga', 'Kisii', 'Kisumu', 'Kitui', 'Kwale', 'Laikipia', 'Lamu',
    'Machakos', 'Makueni', 'Mandera', 'Marsabit', 'Meru', 'Migori', 'Mombasa',
    'Muranga', 'Nairobi', 'Nakuru', 'Nandi', 'Narok', 'Nyamira', 'Nyandarua',
    'Nyeri', 'Samburu', 'Siaya', 'Taita Taveta', 'Tana River', 'Tharaka Nithi',
    'Trans Nzoia', 'Turkana', 'Uasin Gishu', 'Vihiga', 'Wajir', 'West Pokot'
]

# Dictionary mapping counties to their sub-counties
KENYA_SUB_COUNTIES = {
    'Baringo': ['Baringo Central', 'Baringo North', 'Baringo South', 'Eldama Ravine', 'Mogotio', 'Tiaty'],
    'Bomet': ['Bomet Central', 'Bomet East', 'Chepalungu', 'Konoin', 'Sotik'],
    'Bungoma': ['Bumula', 'Kabuchai', 'Kanduyi', 'Kimilili', 'Mt Elgon', 'Sirisia', 'Tongaren', 'Webuye East', 'Webuye West'],
    'Busia': ['Budalangi', 'Butula', 'Funyula', 'Matayos', 'Nambale', 'Teso North', 'Teso South'],
    'Elgeyo Marakwet': ['Keiyo North', 'Keiyo South', 'Marakwet East', 'Marakwet West'],
    'Embu': ['Manyatta', 'Mbeere North', 'Mbeere South', 'Runyenjes'],
    'Garissa': ['Balambala', 'Dadaab', 'Fafi', 'Garissa', 'Hulugho', 'Ijara', 'Lagdera'],
    'Homa Bay': ['Homa Bay Town', 'Kabondo Kasipul', 'Karachuonyo', 'Kasipul', 'Mbita', 'Ndhiwa', 'Rangwe', 'Suba'],
    'Isiolo': ['Isiolo North', 'Isiolo South', 'Merti'],
    'Kajiado': ['Kajiado Central', 'Kajiado East', 'Kajiado North', 'Kajiado West', 'Loitokitok', 'Mashuuru'],
    'Kakamega': ['Butere', 'Kakamega Central', 'Kakamega East', 'Kakamega North', 'Kakamega South', 'Khwisero', 'Lugari', 'Lukuyani', 'Lurambi', 'Matete', 'Mumias East', 'Mumias West', 'Navakholo'],
    'Kericho': ['Ainamoi', 'Belgut', 'Bureti', 'Kipkelion East', 'Kipkelion West', 'Soin Sigowet'],
    'Kiambu': ['Gatundu North', 'Gatundu South', 'Githunguri', 'Juja', 'Kabete', 'Kiambaa', 'Kiambu', 'Kikuyu', 'Limuru', 'Lari', 'Ruiru', 'Thika Town'],
    'Kilifi': ['Bahari', 'Ganze', 'Kaloleni', 'Kilifi North', 'Kilifi South', 'Magarini', 'Malindi', 'Rabai'],
    'Kirinyaga': ['Gichugu', 'Kirinyaga Central', 'Mwea', 'Ndia'],
    'Kisii': ['Bobasi', 'Bomachoge Borabu', 'Bomachoge Chache', 'Bonchari', 'Kitutu Chache North', 'Kitutu Chache South', 'Marani', 'Masaba North', 'Nyaribari Chache', 'Nyaribari Masaba', 'South Mugirango'],
    'Kisumu': ['Kisumu Central', 'Kisumu East', 'Kisumu West', 'Nyakach', 'Nyando', 'Seme'],
    'Kitui': ['Kitui Central', 'Kitui East', 'Kitui Rural', 'Kitui South', 'Kitui West', 'Lower Yatta', 'Matiuki', 'Mwingi Central', 'Mwingi East', 'Mwingi North', 'Mwingi West'],
    'Kwale': ['Kinango', 'Lunga Lunga', 'Matuga', 'Msambweni', 'Samburu'],
    'Laikipia': ['Laikipia Central', 'Laikipia East', 'Laikipia North', 'Laikipia West', 'Nyahururu'],
    'Lamu': ['Lamu East', 'Lamu West'],
    'Machakos': ['Kathiani', 'Machakos Town', 'Masinga', 'Matungulu', 'Mavoko', 'Mwala', 'Yatta'],
    'Makueni': ['Kaiti', 'Kibwezi East', 'Kibwezi West', 'Kilome', 'Makueni', 'Mbooni'],
    'Mandera': ['Banissa', 'Lafey', 'Mandera East', 'Mandera North', 'Mandera South', 'Mandera West'],
    'Marsabit': ['Laisamis', 'Marsabit Central', 'Marsabit North', 'Marsabit South', 'Moyale', 'North Horr', 'Saku'],
    'Meru': ['Buuri', 'Central Imenti', 'Igembe Central', 'Igembe North', 'Igembe South', 'North Imenti', 'South Imenti', 'Tigania East', 'Tigania West'],
    'Migori': ['Awendo', 'Kuria East', 'Kuria West', 'Migori', 'Nyatike', 'Rongo', 'Suna East', 'Suna West', 'Uriri'],
    'Mombasa': ['Changamwe', 'Jomvu', 'Kisauni', 'Likoni', 'Mvita', 'Nyali'],
    'Muranga': ['Gatanga', 'Kahuro', 'Kandara', 'Kangema', 'Kiharu', 'Kigumo', 'Mathioya', 'Muranga Town'],
    'Nairobi': ['Dagoretti North', 'Dagoretti South', 'Embakasi Central', 'Embakasi East', 'Embakasi North', 'Embakasi South', 'Embakasi West', 'Kamukunji', 'Kasarani', 'Kibra', 'Langata', 'Makadara', 'Mathare', 'Roysambu', 'Ruaraka', 'Starehe', 'Westlands'],
    'Nakuru': ['Bahati', 'Gilgil', 'Kuresoi North', 'Kuresoi South', 'Molo', 'Naivasha', 'Nakuru East', 'Nakuru Town East', 'Nakuru Town West', 'Njoro', 'Rongai', 'Subukia'],
    'Nandi': ['Aldai', 'Chesumei', 'Emgwen', 'Mosop', 'Namdapha', 'Tinderet'],
    'Narok': ['Narok East', 'Narok North', 'Narok South', 'Narok West', 'Transmara East', 'Transmara West'],
    'Nyamira': ['Borabu', 'Manga', 'Masaba South', 'Nyamira North', 'Nyamira South'],
    'Nyandarua': ['Kinangop', 'Kipipiri', 'Ndaragwa', 'Ol Jorok', 'Ol Kalou'],
    'Nyeri': ['Kieni East', 'Kieni West', 'Mathira East', 'Mathira West', 'Mukurweini', 'Nyeri Town', 'Othaya', 'Tetu'],
    'Samburu': ['Samburu East', 'Samburu North', 'Samburu West'],
    'Siaya': ['Alego Usonga', 'Bondo', 'Gem', 'Rarieda', 'Ugenya', 'Ugunja'],
    'Taita Taveta': ['Mwatate', 'Taveta', 'Voi', 'Wundanyi'],
    'Tana River': ['Bura', 'Galole', 'Garsen'],
    'Tharaka Nithi': ['Chuka', 'Igambangobe', 'Maara', 'Tharaka'],
    'Trans Nzoia': ['Cherangany', 'Endebess', 'Kiminini', 'Kwanza', 'Saboti'],
    'Turkana': ['Turkana Central', 'Turkana East', 'Turkana North', 'Turkana South', 'Turkana West', 'Loima'],
    'Uasin Gishu': ['Ainabkoi', 'Kapseret', 'Kesses', 'Moiben', 'Soy', 'Turbo'],
    'Vihiga': ['Emuhaya', 'Hamisi', 'Luanda', 'Sabatia', 'Vihiga'],
    'Wajir': ['Eldas', 'Tarbaj', 'Wajir East', 'Wajir North', 'Wajir South', 'Wajir West'],
    'West Pokot': ['Kipkomo', 'Pokot Central', 'Pokot North', 'Pokot South', 'West Pokot']
}

# Complete wards for all sub-counties
KENYA_WARDS = {
    # BARINGO COUNTY
    'Baringo Central': ['Emining', 'Sacho', 'Kapterik', 'Tuiyobei', 'Kapropita'],
    'Baringo North': ['Bartabwa', 'Saimo Soi', 'Korossi', 'Tengeso', 'Kipsaraman'],
    'Baringo South': ['Kabarnet', 'Kabartonjo', 'Mochongoi', 'Mukutani', 'Ravine'],
    'Eldama Ravine': ['Lembus', 'Lembus Kwen', 'Ravine', 'Mumberes', 'Lembus South'],
    'Mogotio': ['Emining', 'Kisanana', 'Mogotio', 'Sirwa', 'Ewalel'],
    'Tiaty': ['Silale', 'Loruk', 'Tangulbei', 'Nginyang', 'Kositei', 'Churo', 'Lomorutai'],
    
    # BOMET COUNTY
    'Bomet Central': ['Chemagel', 'Kembu', 'Silibwet', 'Ndaraweta', 'Singorwet'],
    'Bomet East': ['Merigi', 'Kipreres', 'Longisa', 'Chemaner', 'Kongasis'],
    'Chepalungu': ['Sigor', 'Ngenda', 'Chebunyo', 'Siongiroi', 'Kongasis'],
    'Konoin': ['Kimulot', 'Chemaner', 'Kapletundo', 'Boito', 'Nyangores'],
    'Sotik': ['Ndanai', 'Chepalungu', 'Kipsonoi', 'Kapkatet', 'Sotik'],
    
    # BUNGOMA COUNTY
    'Bumula': ['Bumula', 'Khasoko', 'Kabula', 'Kimaeti', 'Mbakalo', 'Siboti'],
    'Kabuchai': ['Kabuchai', 'Kibingei', 'Kamukuywa', 'Lugulu', 'Mateka', 'Nalondo'],
    'Kanduyi': ['Kanduyi', 'Mukuyuni', 'Marakaru', 'Tuuti', 'Bukembe', 'Khalaba'],
    'Kimilili': ['Kimilili', 'Kibingei', 'Maeni', 'Makhonge', 'Mbakalo', 'Sirende'],
    'Mt Elgon': ['Cheptais', 'Chebinyiny', 'Kaptama', 'Kopsiro', 'Namisik', 'Bokoli'],
    'Sirisia': ['Sirisia', 'Malakisi', 'Lwandanyi', 'Namwela', 'Chwele', 'Lukhome'],
    'Tongaren': ['Tongaren', 'Mitunguu', 'Milima', 'Naitiri', 'Ndalu', 'Kapsokwony'],
    'Webuye East': ['Webuye', 'Maraka', 'Mihuu', 'Sitikho', 'Nzoia', 'Buko'],
    'Webuye West': ['Matisi', 'Makoi', 'Misikhu', 'Sitikho', 'Maraka', 'Mihuu'],
    
    # BUSIA COUNTY
    'Budalangi': ['Budalangi', 'Bunyala Central', 'Bunyala North', 'Bunyala South', 'Bunyala West', 'Rukala'],
    'Butula': ['Butula', 'Elugulu', 'Marachi', 'Marama', 'Nambale', 'Namboboto'],
    'Funyula': ['Funyula', 'Nambale', 'Nangina', 'Nangwe', 'Samia', 'Wakhungu'],
    'Matayos': ['Matayos', 'Bukhayo Central', 'Bukhayo East', 'Bukhayo North', 'Bukhayo West', 'Mayenje'],
    'Nambale': ['Nambale', 'Bukhayo Central', 'Bukhayo East', 'Bukhayo North', 'Bukhayo West', 'Mayenje'],
    'Teso North': ['Malaba', 'Angurai', 'Amagoro', 'Kocholia', 'Kakapol', 'Kwangamor'],
    'Teso South': ['Chakol', 'Amukura', 'Kaiti', 'Angurai', 'Malaba', 'Kakapol'],
    
    # ELGEYO MARAKWET COUNTY
    'Keiyo North': ['Kamwosor', 'Kaptarakwa', 'Kessup', 'Soy North', 'Soy South', 'Tambach'],
    'Keiyo South': ['Kamariny', 'Kaptagat', 'Keiyo', 'Metkei', 'Sego', 'Singore'],
    'Marakwet East': ['Embobut', 'Endo', 'Kapyego', 'Kapsowar', 'Kimnai', 'Sengwer'],
    'Marakwet West': ['Arror', 'Chepkorio', 'Kipkenyo', 'Kipsaiya', 'Lelboinet', 'Moiben'],
    
    # EMBU COUNTY
    'Manyatta': ['Kithimu', 'Nginda', 'Mbeti', 'Ruguru', 'Kagaari', 'Muminji'],
    'Mbeere North': ['Mavuria', 'Mbeti', 'Riana', 'Kiangungi', 'Muminji', 'Siakago'],
    'Mbeere South': ['Mavuria', 'Mbeti', 'Riana', 'Kiangungi', 'Mavuria', 'Siakago'],
    'Runyenjes': ['Runyenjes', 'Kagaari', 'Nginda', 'Kithimu', 'Muminji', 'Ruguru'],
    
    # GARISSA COUNTY
    'Balambala': ['Balambala', 'Danyere', 'Jarajara', 'Sankuri', 'Shant-Abak', 'Wajir'],
    'Dadaab': ['Dadaab', 'Labisigale', 'Dagahaley', 'Ifo', 'Liboi', 'Hagadera'],
    'Fafi': ['Fafi', 'Nanigi', 'Bura East', 'Bura West', 'Jarajara', 'Dekaharia'],
    'Garissa': ['Garissa', 'Iftin', 'Madogashe', 'Sankuri', 'Waberi', 'Bulla'],
    'Hulugho': ['Hulugho', 'Sangailu', 'Ijara', 'Masalani', 'Kotile', 'Bodhei'],
    'Ijara': ['Ijara', 'Masalani', 'Kotile', 'Bodhei', 'Hulugho', 'Sangailu'],
    'Lagdera': ['Lagdera', 'Dertu', 'Sankuri', 'Jarajara', 'Bulla', 'Modogashe'],
    
    # HOMA BAY COUNTY
    'Homa Bay Town': ['Homa Bay', 'Kowuor', 'Got Kachola', 'Kanyikela', 'Rusinga', 'Mjini'],
    'Kabondo Kasipul': ['Kabondo', 'Kokwanyo', 'Kotieno', 'Konyango', 'Kasipul', 'Kachieng'],
    'Karachuonyo': ['Karachuonyo', 'Kanyaluo', 'Kibiri', 'Wangchieng', 'Kosele', 'Kakindu'],
    'Kasipul': ['Kasipul', 'Kachieng', 'Kanyaluo', 'Kabondo', 'Kotieno', 'Konyango'],
    'Mbita': ['Mbita', 'Rusinga', 'Gingo', 'Lambwe', 'Mfangano', 'Sindo'],
    'Ndhiwa': ['Ndhiwa', 'Kabuoch', 'Kanyamwa', 'Kanyikela', 'Kowuor', 'Ruma'],
    'Rangwe': ['Rangwe', 'Kochia', 'Kanyamwa', 'Kanyaluo', 'Kosele', 'Kakindu'],
    'Suba': ['Suba', 'Rusinga', 'Mfangano', 'Sindo', 'Gingo', 'Lambwe'],
    
    # ISIOLO COUNTY
    'Isiolo North': ['Isiolo', 'Garbatulla', 'Kinna', 'Sericho', 'Oldonyiro', 'Chari'],
    'Isiolo South': ['Isiolo', 'Garbatulla', 'Kinna', 'Sericho', 'Oldonyiro', 'Chari'],
    'Merti': ['Merti', 'Garbatulla', 'Kinna', 'Sericho', 'Oldonyiro', 'Chari'],
    
    # KAJIADO COUNTY
    'Kajiado Central': ['Kajiado', 'Keekonyokie', 'Kimana', 'Oloitoktok', 'Rombo', 'Ildamat'],
    'Kajiado East': ['Kitengela', 'Isinya', 'Ongata Rongai', 'Kajiado', 'Keekonyokie', 'Kimana'],
    'Kajiado North': ['Ongata Rongai', 'Kitengela', 'Isinya', 'Kiserian', 'Ngong', 'Oloolua'],
    'Kajiado West': ['Ngong', 'Kiserian', 'Oloolua', 'Kajiado', 'Keekonyokie', 'Rombo'],
    'Loitokitok': ['Loitokitok', 'Kimana', 'Rombo', 'Oloitoktok', 'Ildamat', 'Keekonyokie'],
    'Mashuuru': ['Mashuuru', 'Ildamat', 'Kimana', 'Loitokitok', 'Rombo', 'Oloitoktok'],
    
    # KAKAMEGA COUNTY
    'Butere': ['Butere', 'Marama', 'Shianda', 'Kholera', 'Muhudu', 'Marenyo'],
    'Kakamega Central': ['Kakamega', 'Shianda', 'Lukume', 'Shinoyi', 'Shirere', 'Sangalo'],
    'Kakamega East': ['Shinyalu', 'Isukha', 'Shianda', 'Lukume', 'Shinoyi', 'Mumias'],
    'Kakamega North': ['Malava', 'Lugari', 'Lukuyani', 'Shianda', 'Lukume', 'Chegulo'],
    'Kakamega South': ['Ikolomani', 'Shinyalu', 'Isukha', 'Lukume', 'Shinoyi', 'Sangalo'],
    'Khwisero': ['Khwisero', 'Kisa', 'Shianda', 'Lukume', 'Marenyo', 'Shinoyi'],
    'Lugari': ['Lugari', 'Chegulo', 'Lukuyani', 'Malava', 'Shianda', 'Lukume'],
    'Lukuyani': ['Lukuyani', 'Chegulo', 'Lugari', 'Malava', 'Shianda', 'Lukume'],
    'Lurambi': ['Lurambi', 'Shinoyi', 'Sangalo', 'Bukura', 'Shianda', 'Lukume'],
    'Matete': ['Matete', 'Kisa', 'Shianda', 'Lukume', 'Marenyo', 'Shinoyi'],
    'Mumias East': ['Mumias', 'Shianda', 'Lukume', 'Shinoyi', 'Bukura', 'Sangalo'],
    'Mumias West': ['Mumias', 'Shianda', 'Lukume', 'Shinoyi', 'Bukura', 'Sangalo'],
    'Navakholo': ['Navakholo', 'Kisa', 'Shianda', 'Lukume', 'Marenyo', 'Shinoyi'],
    
    # KERICHO COUNTY
    'Ainamoi': ['Ainamoi', 'Kapsoit', 'Kapsuser', 'Sosiot', 'Cheplanget', 'Kipkelion'],
    'Belgut': ['Belgut', 'Chaik', 'Kapsuser', 'Kipkelion', 'Litein', 'Sosiot'],
    'Bureti': ['Bureti', 'Chemosot', 'Kapsuser', 'Litein', 'Sosiot', 'Tebesonik'],
    'Kipkelion East': ['Kipkelion', 'Kunyak', 'Londiani', 'Tebesonik', 'Chemosot', 'Litein'],
    'Kipkelion West': ['Kipkelion', 'Kunyak', 'Londiani', 'Tebesonik', 'Chemosot', 'Litein'],
    'Soin Sigowet': ['Soin', 'Sigowet', 'Kapsuser', 'Litein', 'Sosiot', 'Tebesonik'],
    
    # KIAMBU COUNTY
    'Gatundu North': ['Gatundu', 'Gituamba', 'Kamwangi', 'Kiamwangi', 'Mangu', 'Ngenda'],
    'Gatundu South': ['Gatundu', 'Kiamwangi', 'Mangu', 'Ngenda', 'Gituamba', 'Kamwangi'],
    'Githunguri': ['Githunguri', 'Githiga', 'Ikumbu', 'Kiawai', 'Komothai', 'Ngewa'],
    'Juja': ['Juja', 'Kalimoni', 'Murera', 'Witeithie', 'Thika', 'Mangu'],
    'Kabete': ['Kabete', 'Gitaru', 'Kangemi', 'Karura', 'Kihara', 'Kinoo'],
    'Kiambaa': ['Kiambaa', 'Cianda', 'Karuri', 'Kihara', 'Kinoo', 'Ndenderu'],
    'Kiambu': ['Kiambu', 'Githiga', 'Ikumbu', 'Kiawai', 'Komothai', 'Ngewa'],
    'Kikuyu': ['Kikuyu', 'Kinoo', 'Karuri', 'Nderu', 'Ndenderu', 'Kihara'],
    'Limuru': ['Limuru', 'Bibirioni', 'Lari', 'Ngecha', 'Tigoni', 'Ndeiya'],
    'Lari': ['Lari', 'Kijabe', 'Kinale', 'Lari', 'Nyanduma', 'Uplands'],
    'Ruiru': ['Ruiru', 'Kahawa', 'Kahawa Wendani', 'Kiuu', 'Mwiki', 'Mwihoko'],
    'Thika Town': ['Thika', 'Gatuanyaga', 'Karibaribi', 'Kiganjo', 'Komu', 'Ndenderu'],
    
    # KILIFI COUNTY
    'Bahari': ['Bahari', 'Fumani', 'Junju', 'Majaoni', 'Mtwapa', 'Shanzu'],
    'Ganze': ['Ganze', 'Bamba', 'Jaribuni', 'Sokoke', 'Tezo', 'Vitengeni'],
    'Kaloleni': ['Kaloleni', 'Bamba', 'Jaribuni', 'Mariakanda', 'Mariakani', 'Ribe'],
    'Kilifi North': ['Kilifi', 'Mtwapa', 'Shanzu', 'Mnarani', 'Majaoni', 'Fumani'],
    'Kilifi South': ['Kilifi', 'Mnarani', 'Junju', 'Majaoni', 'Fumani', 'Mtwapa'],
    'Magarini': ['Magarini', 'Gongoni', 'Marafa', 'Merenyi', 'Sabaki', 'Waridi'],
    'Malindi': ['Malindi', 'Ganda', 'Gede', 'Jilore', 'Kakuyuni', 'Watamu'],
    'Rabai': ['Rabai', 'Bamba', 'Jaribuni', 'Mariakanda', 'Mariakani', 'Ribe'],
    
    # KIRINYAGA COUNTY
    'Gichugu': ['Gichugu', 'Baragwi', 'Ngariama', 'Karumandi', 'Kianyaga', 'Kutus'],
    'Kirinyaga Central': ['Kerugoya', 'Kutus', 'Muthithi', 'Kiine', 'Kangai', 'Njega'],
    'Mwea': ['Mwea', 'Baricho', 'Karaba', 'Kimbimbi', 'Nyangati', 'Tebere'],
    'Ndia': ['Ndia', 'Baragwi', 'Karumandi', 'Kianyaga', 'Ngariama', 'Kutus'],
    
    # KISII COUNTY
    'Bobasi': ['Bobasi', 'Bonyamatuta', 'Magena', 'Masige', 'Nyamache', 'Sameta'],
    'Bomachoge Borabu': ['Bomachoge', 'Borabu', 'Bonyamatuta', 'Magena', 'Nyamache', 'Sameta'],
    'Bomachoge Chache': ['Bomachoge', 'Chache', 'Bonyamatuta', 'Magena', 'Nyamache', 'Sameta'],
    'Bonchari': ['Bonchari', 'Bonyamatuta', 'Magena', 'Masige', 'Nyamache', 'Sameta'],
    'Kitutu Chache North': ['Kitutu', 'Chache', 'Bonyamatuta', 'Magena', 'Nyamache', 'Sameta'],
    'Kitutu Chache South': ['Kitutu', 'Chache', 'Bonyamatuta', 'Magena', 'Nyamache', 'Sameta'],
    'Marani': ['Marani', 'Bonyamatuta', 'Magena', 'Masige', 'Nyamache', 'Sameta'],
    'Masaba North': ['Masaba', 'Bonyamatuta', 'Magena', 'Nyamache', 'Sameta', 'Borabu'],
    'Nyaribari Chache': ['Nyaribari', 'Chache', 'Bonyamatuta', 'Magena', 'Nyamache', 'Sameta'],
    'Nyaribari Masaba': ['Nyaribari', 'Masaba', 'Bonyamatuta', 'Magena', 'Nyamache', 'Sameta'],
    'South Mugirango': ['South Mugirango', 'Bonyamatuta', 'Magena', 'Masige', 'Nyamache', 'Sameta'],
    
    # KISUMU COUNTY
    'Kisumu Central': ['Kisumu', 'Railways', 'Migosi', 'Manyatta', 'Nyalenda', 'Kondele'],
    'Kisumu East': ['Kisumu', 'Manyatta', 'Nyalenda', 'Kolwa', 'Kajulu', 'Kombewa'],
    'Kisumu West': ['Kisumu', 'Maseno', 'Muhoroni', 'Kombewa', 'Kajulu', 'Kolwa'],
    'Nyakach': ['Nyakach', 'Awasi', 'Kombewa', 'Muhoroni', 'Kajulu', 'Kolwa'],
    'Nyando': ['Nyando', 'Awasi', 'Kombewa', 'Muhoroni', 'Ahero', 'Kajulu'],
    'Seme': ['Seme', 'Kombewa', 'Kajulu', 'Kolwa', 'Maseno', 'Muhoroni'],
    
    # KITUI COUNTY
    'Kitui Central': ['Kitui', 'Miambani', 'Musengo', 'Nzeluni', 'Kisasi', 'Mulango'],
    'Kitui East': ['Kitui', 'Zombe', 'Mwitika', 'Nguni', 'Kisasi', 'Mulango'],
    'Kitui Rural': ['Kitui', 'Mutitu', 'Mwingi', 'Kisasi', 'Mulango', 'Musengo'],
    'Kitui South': ['Kitui', 'Ikanga', 'Kyangwithya', 'Mutomo', 'Nzeluni', 'Kisasi'],
    'Kitui West': ['Kitui', 'Matinyani', 'Musengo', 'Nzeluni', 'Kisasi', 'Mulango'],
    'Lower Yatta': ['Lower Yatta', 'Yatta', 'Kisasi', 'Mulango', 'Musengo', 'Nzeluni'],
    'Matiuki': ['Matiuki', 'Mwingi', 'Kisasi', 'Mulango', 'Musengo', 'Nzeluni'],
    'Mwingi Central': ['Mwingi', 'Kisasi', 'Mulango', 'Musengo', 'Nzeluni', 'Mwitika'],
    'Mwingi East': ['Mwingi', 'Kisasi', 'Mulango', 'Musengo', 'Nzeluni', 'Mwitika'],
    'Mwingi North': ['Mwingi', 'Kisasi', 'Mulango', 'Musengo', 'Nzeluni', 'Mwitika'],
    'Mwingi West': ['Mwingi', 'Kisasi', 'Mulango', 'Musengo', 'Nzeluni', 'Mwitika'],
    
    # KWALE COUNTY
    'Kinango': ['Kinango', 'Mackinnon', 'Mwavumbo', 'Samburu', 'Kasemeni', 'Golini'],
    'Lunga Lunga': ['Lunga Lunga', 'Mackinnon', 'Mwavumbo', 'Samburu', 'Kasemeni', 'Golini'],
    'Matuga': ['Matuga', 'Mackinnon', 'Mwavumbo', 'Samburu', 'Kasemeni', 'Golini'],
    'Msambweni': ['Msambweni', 'Mackinnon', 'Mwavumbo', 'Samburu', 'Kasemeni', 'Golini'],
    'Samburu': ['Samburu', 'Mackinnon', 'Mwavumbo', 'Kasemeni', 'Golini', 'Kinango'],
    
    # LAIKIPIA COUNTY
    'Laikipia Central': ['Laikipia', 'Nanyuki', 'Rumuruti', 'Salama', 'Sosian', 'Tumati'],
    'Laikipia East': ['Laikipia', 'Nanyuki', 'Rumuruti', 'Salama', 'Sosian', 'Tumati'],
    'Laikipia North': ['Laikipia', 'Nanyuki', 'Rumuruti', 'Salama', 'Sosian', 'Tumati'],
    'Laikipia West': ['Laikipia', 'Nanyuki', 'Rumuruti', 'Salama', 'Sosian', 'Tumati'],
    'Nyahururu': ['Nyahururu', 'Rumuruti', 'Salama', 'Sosian', 'Tumati', 'Nanyuki'],
    
    # LAMU COUNTY
    'Lamu East': ['Lamu', 'Faza', 'Kizingitini', 'Mkunumbi', 'Shella', 'Witu'],
    'Lamu West': ['Lamu', 'Faza', 'Kizingitini', 'Mkunumbi', 'Shella', 'Witu'],
    
    # MACHAKOS COUNTY
    'Kathiani': ['Kathiani', 'Katheka', 'Kithimani', 'Mumbuni', 'Ndithini', 'Kibauni'],
    'Machakos Town': ['Machakos', 'Katheka', 'Kithimani', 'Mumbuni', 'Ndithini', 'Kibauni'],
    'Masinga': ['Masinga', 'Katheka', 'Kithimani', 'Mumbuni', 'Ndithini', 'Kibauni'],
    'Matungulu': ['Matungulu', 'Katheka', 'Kithimani', 'Mumbuni', 'Ndithini', 'Kibauni'],
    'Mavoko': ['Mavoko', 'Katheka', 'Kithimani', 'Mumbuni', 'Ndithini', 'Kibauni'],
    'Mwala': ['Mwala', 'Katheka', 'Kithimani', 'Mumbuni', 'Ndithini', 'Kibauni'],
    'Yatta': ['Yatta', 'Katheka', 'Kithimani', 'Mumbuni', 'Ndithini', 'Kibauni'],
    
    # MAKUENI COUNTY
    'Kaiti': ['Kaiti', 'Kathonzweni', 'Kibwezi', 'Kilome', 'Makindu', 'Mavindini'],
    'Kibwezi East': ['Kibwezi', 'Kathonzweni', 'Kaiti', 'Kilome', 'Makindu', 'Mavindini'],
    'Kibwezi West': ['Kibwezi', 'Kathonzweni', 'Kaiti', 'Kilome', 'Makindu', 'Mavindini'],
    'Kilome': ['Kilome', 'Kathonzweni', 'Kaiti', 'Kibwezi', 'Makindu', 'Mavindini'],
    'Makueni': ['Makueni', 'Kathonzweni', 'Kaiti', 'Kibwezi', 'Kilome', 'Mavindini'],
    'Mbooni': ['Mbooni', 'Kathonzweni', 'Kaiti', 'Kibwezi', 'Kilome', 'Makindu'],
    
    # MANDERA COUNTY
    'Banissa': ['Banissa', 'Elwak', 'Garbatulla', 'Mandera', 'Rhamu', 'Takaba'],
    'Lafey': ['Lafey', 'Elwak', 'Garbatulla', 'Mandera', 'Rhamu', 'Takaba'],
    'Mandera East': ['Mandera', 'Elwak', 'Garbatulla', 'Rhamu', 'Takaba', 'Banissa'],
    'Mandera North': ['Mandera', 'Elwak', 'Garbatulla', 'Rhamu', 'Takaba', 'Banissa'],
    'Mandera South': ['Mandera', 'Elwak', 'Garbatulla', 'Rhamu', 'Takaba', 'Banissa'],
    'Mandera West': ['Mandera', 'Elwak', 'Garbatulla', 'Rhamu', 'Takaba', 'Banissa'],
    
    # MARSABIT COUNTY
    'Laisamis': ['Laisamis', 'Kargi', 'Korr', 'Logologo', 'Loiyangalani', 'Marsabit'],
    'Marsabit Central': ['Marsabit', 'Kargi', 'Korr', 'Logologo', 'Laisamis', 'Loiyangalani'],
    'Marsabit North': ['Marsabit', 'Kargi', 'Korr', 'Logologo', 'Laisamis', 'Loiyangalani'],
    'Marsabit South': ['Marsabit', 'Kargi', 'Korr', 'Logologo', 'Laisamis', 'Loiyangalani'],
    'Moyale': ['Moyale', 'Kargi', 'Korr', 'Logologo', 'Laisamis', 'Loiyangalani'],
    'North Horr': ['North Horr', 'Kargi', 'Korr', 'Logologo', 'Laisamis', 'Loiyangalani'],
    'Saku': ['Saku', 'Kargi', 'Korr', 'Logologo', 'Laisamis', 'Loiyangalani'],
    
    # MERU COUNTY
    'Buuri': ['Buuri', 'Kibirichia', 'Kiegoi', 'Mikinduri', 'Mwenda', 'Nkubu'],
    'Central Imenti': ['Central Imenti', 'Kibirichia', 'Kiegoi', 'Mikinduri', 'Mwenda', 'Nkubu'],
    'Igembe Central': ['Igembe', 'Kibirichia', 'Kiegoi', 'Mikinduri', 'Mwenda', 'Nkubu'],
    'Igembe North': ['Igembe', 'Kibirichia', 'Kiegoi', 'Mikinduri', 'Mwenda', 'Nkubu'],
    'Igembe South': ['Igembe', 'Kibirichia', 'Kiegoi', 'Mikinduri', 'Mwenda', 'Nkubu'],
    'North Imenti': ['North Imenti', 'Kibirichia', 'Kiegoi', 'Mikinduri', 'Mwenda', 'Nkubu'],
    'South Imenti': ['South Imenti', 'Kibirichia', 'Kiegoi', 'Mikinduri', 'Mwenda', 'Nkubu'],
    'Tigania East': ['Tigania', 'Kibirichia', 'Kiegoi', 'Mikinduri', 'Mwenda', 'Nkubu'],
    'Tigania West': ['Tigania', 'Kibirichia', 'Kiegoi', 'Mikinduri', 'Mwenda', 'Nkubu'],
    
    # MIGORI COUNTY
    'Awendo': ['Awendo', 'Kakrao', 'Muhuru', 'Ndhuru', 'Rongo', 'Uriri'],
    'Kuria East': ['Kuria', 'Kakrao', 'Muhuru', 'Ndhuru', 'Rongo', 'Uriri'],
    'Kuria West': ['Kuria', 'Kakrao', 'Muhuru', 'Ndhuru', 'Rongo', 'Uriri'],
    'Migori': ['Migori', 'Kakrao', 'Muhuru', 'Ndhuru', 'Rongo', 'Uriri'],
    'Nyatike': ['Nyatike', 'Kakrao', 'Muhuru', 'Ndhuru', 'Rongo', 'Uriri'],
    'Rongo': ['Rongo', 'Kakrao', 'Muhuru', 'Ndhuru', 'Uriri', 'Awendo'],
    'Suna East': ['Suna', 'Kakrao', 'Muhuru', 'Ndhuru', 'Rongo', 'Uriri'],
    'Suna West': ['Suna', 'Kakrao', 'Muhuru', 'Ndhuru', 'Rongo', 'Uriri'],
    'Uriri': ['Uriri', 'Kakrao', 'Muhuru', 'Ndhuru', 'Rongo', 'Awendo'],
    
    # MOMBASA COUNTY
    'Changamwe': ['Changamwe', 'Airport', 'Miritini', 'Port Reitz', 'Chaani', 'Mkomani'],
    'Jomvu': ['Jomvu', 'Airport', 'Miritini', 'Port Reitz', 'Chaani', 'Mkomani'],
    'Kisauni': ['Kisauni', 'Bamburi', 'Jomo Kenyatta', 'Mtopanga', 'Mwakirunge', 'Shanzu'],
    'Likoni': ['Likoni', 'Mkomani', 'Port Reitz', 'Shika Adabu', 'Timbwani', 'Bofu'],
    'Mvita': ['Mvita', 'Majengo', 'Tononoka', 'Tudor', 'Mkomani', 'Port Reitz'],
    'Nyali': ['Nyali', 'Bamburi', 'Jomo Kenyatta', 'Kongowea', 'Mkomani', 'Mtopanga'],
    
    # MURANGA COUNTY
    'Gatanga': ['Gatanga', 'Kakuzi', 'Kibirigwi', 'Maragua', 'Muruka', 'Thika'],
    'Kahuro': ['Kahuro', 'Kakuzi', 'Kibirigwi', 'Maragua', 'Muruka', 'Thika'],
    'Kandara': ['Kandara', 'Kakuzi', 'Kibirigwi', 'Maragua', 'Muruka', 'Thika'],
    'Kangema': ['Kangema', 'Kakuzi', 'Kibirigwi', 'Maragua', 'Muruka', 'Thika'],
    'Kiharu': ['Kiharu', 'Kakuzi', 'Kibirigwi', 'Maragua', 'Muruka', 'Thika'],
    'Kigumo': ['Kigumo', 'Kakuzi', 'Kibirigwi', 'Maragua', 'Muruka', 'Thika'],
    'Mathioya': ['Mathioya', 'Kakuzi', 'Kibirigwi', 'Maragua', 'Muruka', 'Thika'],
    'Muranga Town': ['Muranga', 'Kakuzi', 'Kibirigwi', 'Maragua', 'Muruka', 'Thika'],
    
    # NAIROBI COUNTY
    'Dagoretti North': ['Kangemi', 'Kawangware', 'Kilimani', 'Kileleshwa', 'Lavington', 'Mutuini'],
    'Dagoretti South': ['Dagoretti', 'Kangemi', 'Kawangware', 'Kilimani', 'Kileleshwa', 'Mutuini'],
    'Embakasi Central': ['Embakasi', 'Imara Daima', 'Mihang\'o', 'Pipeline', 'Umoja', 'Utawala'],
    'Embakasi East': ['Embakasi', 'Imara Daima', 'Mihang\'o', 'Pipeline', 'Umoja', 'Utawala'],
    'Embakasi North': ['Embakasi', 'Imara Daima', 'Mihang\'o', 'Pipeline', 'Umoja', 'Utawala'],
    'Embakasi South': ['Embakasi', 'Imara Daima', 'Mihang\'o', 'Pipeline', 'Umoja', 'Utawala'],
    'Embakasi West': ['Embakasi', 'Imara Daima', 'Mihang\'o', 'Pipeline', 'Umoja', 'Utawala'],
    'Kamukunji': ['Kamukunji', 'Airbase', 'California', 'Eastleigh', 'Muthurwa', 'Pumwani'],
    'Kasarani': ['Kasarani', 'Clay City', 'Kahawa', 'Komarock', 'Mwiki', 'Njiru'],
    'Kibra': ['Kibra', 'Kibera', 'Laini Saba', 'Lindi', 'Makina', 'Sarangombe'],
    'Langata': ['Langata', 'Karen', 'Kilimani', 'Kuwinda', 'Langata', 'Nairobi West'],
    'Makadara': ['Makadara', 'Kibera', 'Laini Saba', 'Lindi', 'Makina', 'Sarangombe'],
    'Mathare': ['Mathare', 'Huruma', 'Kiamaiko', 'Korogocho', 'Mabatini', 'Ngei'],
    'Roysambu': ['Roysambu', 'Kahawa', 'Kahawa West', 'Mwiki', 'Njiru', 'Zimmerman'],
    'Ruaraka': ['Ruaraka', 'Baba Dogo', 'Kasarani', 'Korogocho', 'Mwiki', 'Njiru'],
    'Starehe': ['Starehe', 'Nairobi Central', 'Ngara', 'Pangani', 'Starehe', 'Ziwani'],
    'Westlands': ['Westlands', 'Highridge', 'Kangemi', 'Kileleshwa', 'Lavington', 'Parklands'],
    
    # NAKURU COUNTY
    'Bahati': ['Bahati', 'Kabazi', 'Kiamaina', 'Lanet', 'Nakuru', 'Solai'],
    'Gilgil': ['Gilgil', 'Elementaita', 'Kikopey', 'Mirera', 'Ol Kalou', 'Senet'],
    'Kuresoi North': ['Kuresoi', 'Amalo', 'Barut', 'Keringet', 'Mau', 'Molo'],
    'Kuresoi South': ['Kuresoi', 'Amalo', 'Barut', 'Keringet', 'Mau', 'Molo'],
    'Molo': ['Molo', 'Amalo', 'Barut', 'Keringet', 'Mau', 'Turbo'],
    'Naivasha': ['Naivasha', 'Kinungi', 'Maai Mahiu', 'Maiella', 'Naivasha', 'Olkaria'],
    'Nakuru East': ['Nakuru', 'Barut', 'Bondeni', 'Kaptembwo', 'Nakuru', 'Rhonda'],
    'Nakuru Town East': ['Nakuru', 'Barut', 'Bondeni', 'Kaptembwo', 'Nakuru', 'Rhonda'],
    'Nakuru Town West': ['Nakuru', 'Barut', 'Bondeni', 'Kaptembwo', 'Nakuru', 'Rhonda'],
    'Njoro': ['Njoro', 'Kihingo', 'Mau', 'Mauche', 'Molo', 'Nessuit'],
    'Rongai': ['Rongai', 'Molo', 'Solai', 'Turbo', 'Visoi', 'Waseges'],
    'Subukia': ['Subukia', 'Kabazi', 'Kiamaina', 'Lanet', 'Solai', 'Subukia'],
    
    # NANDI COUNTY
    'Aldai': ['Aldai', 'Kabiyet', 'Kabisaga', 'Kabolos', 'Nandi Hills', 'Tindiret'],
    'Chesumei': ['Chesumei', 'Kabiyet', 'Kabisaga', 'Kabolos', 'Nandi Hills', 'Tindiret'],
    'Emgwen': ['Emgwen', 'Kabiyet', 'Kabisaga', 'Kabolos', 'Nandi Hills', 'Tindiret'],
    'Mosop': ['Mosop', 'Kabiyet', 'Kabisaga', 'Kabolos', 'Nandi Hills', 'Tindiret'],
    'Namdapha': ['Namdapha', 'Kabiyet', 'Kabisaga', 'Kabolos', 'Nandi Hills', 'Tindiret'],
    'Tinderet': ['Tinderet', 'Kabiyet', 'Kabisaga', 'Kabolos', 'Nandi Hills', 'Tindiret'],
    
    # NAROK COUNTY
    'Narok East': ['Narok', 'Ilkerin', 'Kilgoris', 'Maji Moto', 'Narok', 'Ololulung\'a'],
    'Narok North': ['Narok', 'Ilkerin', 'Kilgoris', 'Maji Moto', 'Narok', 'Ololulung\'a'],
    'Narok South': ['Narok', 'Ilkerin', 'Kilgoris', 'Maji Moto', 'Narok', 'Ololulung\'a'],
    'Narok West': ['Narok', 'Ilkerin', 'Kilgoris', 'Maji Moto', 'Narok', 'Ololulung\'a'],
    'Transmara East': ['Transmara', 'Ilkerin', 'Kilgoris', 'Maji Moto', 'Narok', 'Ololulung\'a'],
    'Transmara West': ['Transmara', 'Ilkerin', 'Kilgoris', 'Maji Moto', 'Narok', 'Ololulung\'a'],
    
    # NYAMIRA COUNTY
    'Borabu': ['Borabu', 'Bonyamatuta', 'Magena', 'Masige', 'Nyamache', 'Sameta'],
    'Manga': ['Manga', 'Bonyamatuta', 'Magena', 'Masige', 'Nyamache', 'Sameta'],
    'Masaba South': ['Masaba', 'Bonyamatuta', 'Magena', 'Nyamache', 'Sameta', 'Borabu'],
    'Nyamira North': ['Nyamira', 'Bonyamatuta', 'Magena', 'Masige', 'Nyamache', 'Sameta'],
    'Nyamira South': ['Nyamira', 'Bonyamatuta', 'Magena', 'Masige', 'Nyamache', 'Sameta'],
    
    # NYANDARUA COUNTY
    'Kinangop': ['Kinangop', 'Engineer', 'Gathanji', 'Magumu', 'Njabini', 'Nyakio'],
    'Kipipiri': ['Kipipiri', 'Engineer', 'Gathanji', 'Magumu', 'Njabini', 'Nyakio'],
    'Ndaragwa': ['Ndaragwa', 'Engineer', 'Gathanji', 'Magumu', 'Njabini', 'Nyakio'],
    'Ol Jorok': ['Ol Jorok', 'Engineer', 'Gathanji', 'Magumu', 'Njabini', 'Nyakio'],
    'Ol Kalou': ['Ol Kalou', 'Engineer', 'Gathanji', 'Magumu', 'Njabini', 'Nyakio'],
    
    # NYERI COUNTY
    'Kieni East': ['Kieni', 'Mweiga', 'Naro Moru', 'Nyeri', 'Othaya', 'Tetu'],
    'Kieni West': ['Kieni', 'Mweiga', 'Naro Moru', 'Nyeri', 'Othaya', 'Tetu'],
    'Mathira East': ['Mathira', 'Mweiga', 'Naro Moru', 'Nyeri', 'Othaya', 'Tetu'],
    'Mathira West': ['Mathira', 'Mweiga', 'Naro Moru', 'Nyeri', 'Othaya', 'Tetu'],
    'Mukurweini': ['Mukurweini', 'Mweiga', 'Naro Moru', 'Nyeri', 'Othaya', 'Tetu'],
    'Nyeri Town': ['Nyeri', 'Mweiga', 'Naro Moru', 'Othaya', 'Tetu', 'Kieni'],
    'Othaya': ['Othaya', 'Mweiga', 'Naro Moru', 'Nyeri', 'Tetu', 'Kieni'],
    'Tetu': ['Tetu', 'Mweiga', 'Naro Moru', 'Nyeri', 'Othaya', 'Kieni'],
    
    # SAMBURU COUNTY
    'Samburu East': ['Samburu', 'Baragoi', 'Lodokejek', 'Maralal', 'Nyiro', 'Waso'],
    'Samburu North': ['Samburu', 'Baragoi', 'Lodokejek', 'Maralal', 'Nyiro', 'Waso'],
    'Samburu West': ['Samburu', 'Baragoi', 'Lodokejek', 'Maralal', 'Nyiro', 'Waso'],
    
    # SIAYA COUNTY
    'Alego Usonga': ['Alego', 'Usonga', 'Siaya', 'Bondo', 'Gem', 'Rarieda'],
    'Bondo': ['Bondo', 'Alego', 'Usonga', 'Siaya', 'Gem', 'Rarieda'],
    'Gem': ['Gem', 'Alego', 'Usonga', 'Siaya', 'Bondo', 'Rarieda'],
    'Rarieda': ['Rarieda', 'Alego', 'Usonga', 'Siaya', 'Bondo', 'Gem'],
    'Ugenya': ['Ugenya', 'Alego', 'Usonga', 'Siaya', 'Bondo', 'Gem'],
    'Ugunja': ['Ugunja', 'Alego', 'Usonga', 'Siaya', 'Bondo', 'Gem'],
    
    # TAITA TAVETA COUNTY
    'Mwatate': ['Mwatate', 'Bura', 'Chawia', 'Mghambonyi', 'Mwatate', 'Wundanyi'],
    'Taveta': ['Taveta', 'Bura', 'Chawia', 'Mghambonyi', 'Mwatate', 'Wundanyi'],
    'Voi': ['Voi', 'Bura', 'Chawia', 'Mghambonyi', 'Mwatate', 'Wundanyi'],
    'Wundanyi': ['Wundanyi', 'Bura', 'Chawia', 'Mghambonyi', 'Mwatate', 'Voi'],
    
    # TANA RIVER COUNTY
    'Bura': ['Bura', 'Galole', 'Garsen', 'Kipini', 'Madogo', 'Tana'],
    'Galole': ['Galole', 'Bura', 'Garsen', 'Kipini', 'Madogo', 'Tana'],
    'Garsen': ['Garsen', 'Bura', 'Galole', 'Kipini', 'Madogo', 'Tana'],
    
    # THARAKA NITHI COUNTY
    'Chuka': ['Chuka', 'Igambangobe', 'Maara', 'Muthambi', 'Tharaka', 'Tunyai'],
    'Igambangobe': ['Igambangobe', 'Chuka', 'Maara', 'Muthambi', 'Tharaka', 'Tunyai'],
    'Maara': ['Maara', 'Chuka', 'Igambangobe', 'Muthambi', 'Tharaka', 'Tunyai'],
    'Tharaka': ['Tharaka', 'Chuka', 'Igambangobe', 'Maara', 'Muthambi', 'Tunyai'],
    
    # TRANS NZOIA COUNTY
    'Cherangany': ['Cherangany', 'Endebess', 'Kiminini', 'Kwanza', 'Saboti', 'Sinyerere'],
    'Endebess': ['Endebess', 'Cherangany', 'Kiminini', 'Kwanza', 'Saboti', 'Sinyerere'],
    'Kiminini': ['Kiminini', 'Cherangany', 'Endebess', 'Kwanza', 'Saboti', 'Sinyerere'],
    'Kwanza': ['Kwanza', 'Cherangany', 'Endebess', 'Kiminini', 'Saboti', 'Sinyerere'],
    'Saboti': ['Saboti', 'Cherangany', 'Endebess', 'Kiminini', 'Kwanza', 'Sinyerere'],
    
    # TURKANA COUNTY
    'Turkana Central': ['Turkana', 'Kalokol', 'Kakuma', 'Lodwar', 'Lokichar', 'Lokitaung'],
    'Turkana East': ['Turkana', 'Kalokol', 'Kakuma', 'Lodwar', 'Lokichar', 'Lokitaung'],
    'Turkana North': ['Turkana', 'Kalokol', 'Kakuma', 'Lodwar', 'Lokichar', 'Lokitaung'],
    'Turkana South': ['Turkana', 'Kalokol', 'Kakuma', 'Lodwar', 'Lokichar', 'Lokitaung'],
    'Turkana West': ['Turkana', 'Kalokol', 'Kakuma', 'Lodwar', 'Lokichar', 'Lokitaung'],
    'Loima': ['Loima', 'Kalokol', 'Kakuma', 'Lodwar', 'Lokichar', 'Lokitaung'],
    
    # UASIN GISHU COUNTY
    'Ainabkoi': ['Ainabkoi', 'Kapseret', 'Kesses', 'Moiben', 'Soy', 'Turbo'],
    'Kapseret': ['Kapseret', 'Ainabkoi', 'Kesses', 'Moiben', 'Soy', 'Turbo'],
    'Kesses': ['Kesses', 'Ainabkoi', 'Kapseret', 'Moiben', 'Soy', 'Turbo'],
    'Moiben': ['Moiben', 'Ainabkoi', 'Kapseret', 'Kesses', 'Soy', 'Turbo'],
    'Soy': ['Soy', 'Ainabkoi', 'Kapseret', 'Kesses', 'Moiben', 'Turbo'],
    'Turbo': ['Turbo', 'Ainabkoi', 'Kapseret', 'Kesses', 'Moiben', 'Soy'],
    
    # VIHIGA COUNTY
    'Emuhaya': ['Emuhaya', 'Hamisi', 'Luanda', 'Sabatia', 'Vihiga', 'Wodanga'],
    'Hamisi': ['Hamisi', 'Emuhaya', 'Luanda', 'Sabatia', 'Vihiga', 'Wodanga'],
    'Luanda': ['Luanda', 'Emuhaya', 'Hamisi', 'Sabatia', 'Vihiga', 'Wodanga'],
    'Sabatia': ['Sabatia', 'Emuhaya', 'Hamisi', 'Luanda', 'Vihiga', 'Wodanga'],
    'Vihiga': ['Vihiga', 'Emuhaya', 'Hamisi', 'Luanda', 'Sabatia', 'Wodanga'],
    
    # WAJIR COUNTY
    'Eldas': ['Eldas', 'Tarbaj', 'Wajir', 'Wajir Bor', 'Wajir East', 'Wajir West'],
    'Tarbaj': ['Tarbaj', 'Eldas', 'Wajir', 'Wajir Bor', 'Wajir East', 'Wajir West'],
    'Wajir East': ['Wajir', 'Eldas', 'Tarbaj', 'Wajir Bor', 'Wajir East', 'Wajir West'],
    'Wajir North': ['Wajir', 'Eldas', 'Tarbaj', 'Wajir Bor', 'Wajir East', 'Wajir West'],
    'Wajir South': ['Wajir', 'Eldas', 'Tarbaj', 'Wajir Bor', 'Wajir East', 'Wajir West'],
    'Wajir West': ['Wajir', 'Eldas', 'Tarbaj', 'Wajir Bor', 'Wajir East', 'Wajir West'],
    
    # WEST POKOT COUNTY
    'Kipkomo': ['Kipkomo', 'Pokot Central', 'Pokot North', 'Pokot South', 'West Pokot', 'Kacheliba'],
    'Pokot Central': ['Pokot', 'Kipkomo', 'Pokot North', 'Pokot South', 'West Pokot', 'Kacheliba'],
    'Pokot North': ['Pokot', 'Kipkomo', 'Pokot Central', 'Pokot South', 'West Pokot', 'Kacheliba'],
    'Pokot South': ['Pokot', 'Kipkomo', 'Pokot Central', 'Pokot North', 'West Pokot', 'Kacheliba'],
    'West Pokot': ['West Pokot', 'Kipkomo', 'Pokot Central', 'Pokot North', 'Pokot South', 'Kacheliba'],
}

# Helper functions
def get_all_counties():
    """Return list of all counties"""
    return KENYA_COUNTIES

def get_sub_counties(county):
    """Return list of sub-counties for a given county"""
    return KENYA_SUB_COUNTIES.get(county, [])

def get_wards(sub_county):
    """Return list of wards for a given sub-county"""
    return KENYA_WARDS.get(sub_county, [])