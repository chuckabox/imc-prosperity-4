import pandas as pd
df = pd.read_csv("ROUND 1/data/data_capsule/prices_round_1_day_0.csv", sep=';')
print("Zero mid_price count for OSMIUM:", len(df[(df['product'] == 'ASH_COATED_OSMIUM') & (df['mid_price'] == 0)]))
print("Zero mid_price count for PEPPER:", len(df[(df['product'] == 'INTARIAN_PEPPER_ROOT') & (df['mid_price'] == 0)]))

print("\nNon-zero Mid Price Stats for OSMIUM:")
os_nonzero = df[(df['product'] == 'ASH_COATED_OSMIUM') & (df['mid_price'] > 0)]['mid_price']
print(os_nonzero.describe())

print("\nNon-zero Mid Price Stats for PEPPER:")
pep_nonzero = df[(df['product'] == 'INTARIAN_PEPPER_ROOT') & (df['mid_price'] > 0)]['mid_price']
print(pep_nonzero.describe())
